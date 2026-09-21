import json
import socket
import threading
import time
import urllib.request

import uvicorn
import test_category_management as fixtures
import main
import unittest


class CategoryHttpTests(unittest.TestCase):
    setUp = fixtures.CategoryTests.setUp
    tearDown = fixtures.CategoryTests.tearDown
    # Only this HTTP test uses the parent fixture; unit cases remain in their own class.
    def test_http_editor_profile_scan_and_history(self):
        sock=socket.socket();sock.bind(('127.0.0.1',0))
        base='http://127.0.0.1:'+str(sock.getsockname()[1])
        server=uvicorn.Server(uvicorn.Config(main.app, log_level='critical', lifespan='on'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
        thread.start()
        def request(path, body=None, method='GET'):
            data=None if body is None else json.dumps(body).encode()
            req=urllib.request.Request(base+path,data=data,method=method,headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=5) as response:
                return json.load(response)
        try:
            for _ in range(100):
                if server.started: break
                time.sleep(.01)
            self.assertTrue(server.started)
            status=request('/api/category-management')['data']
            self.assertEqual(status['revision'],__import__('category_management').digest(status['categories']))
            updated=request('/api/category-management/profile',{'role':'QA engineer','intervalHours':0},'PUT')
            self.assertTrue(updated['ok'])
            cats=status['categories'];cats[0]['name']='Defects'
            result=request('/api/categories?revision='+status['revision'],cats,'PUT')
            self.assertTrue(result['ok'])
            history=request('/api/category-management')['data']['history']
            restored=request('/api/category-management/restore/'+history[0]['id'],{},'POST')
            self.assertTrue(restored['ok'])
            self.assertEqual(restored['data']['categories'][0]['name'],'Bugs')
            bad=request('/api/category-management/profile',{'role':'QA','intervalHours':1},'PUT')
            self.assertFalse(bad['ok'])
        finally:
            server.should_exit=True
            thread.join(timeout=5)
            sock.close()
            self.assertFalse(thread.is_alive())
