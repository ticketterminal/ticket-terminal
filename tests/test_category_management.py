import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import category_management as cm
import content
import db
from workspace_fixture import TempWorkspaces


def category(cid, name=None, docs=None):
    return {'id': cid, 'name': name or cid.title(), 'status':'gap', 'color':'#4E79A7',
            'note':'', 'docs': docs or [], 'skills':[], 'memories':[]}

class CategoryTests(unittest.TestCase):
    def setUp(self):
        # A temp data root with the "default" workspace entered: db.json,
        # categories.json and category-management.json all land in it.
        self.workspaces = TempWorkspaces().start()
        self.root = self.workspaces.root
        self.patches = []
        for p in self.patches: p.start()
        content.write_categories([category('bugs', docs=['bug-guide']), category('features', docs=['feature-guide'])])
        db.write({'jiraTickets': {'T-1': {'key':'T-1','summary':'Fix login','categories':['bugs'],'notes':[{'text':'original'}], 'codexSessionId':'session'},
                                  'T-2': {'key':'T-2','summary':'New feature','categories':['features']}}, 'people':{},'teamOptions':[]})

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.workspaces.stop()

    def scan(self, suggestions):
        cm.SCAN_LOCK.acquire()
        with patch.object(cm, 'ask_llm', return_value={'suggestions': suggestions}):
            cm.scan_worker()
        result=cm.status()
        self.assertEqual(result['scan']['status'],'done',result['scan'])
        return result['reviews'][0]

    def accept(self, review, items=None):
        return cm.decide(review['id'], {'decision':'accept','suggestionIds':items or [s['suggestionId'] for s in review['suggestions']]})

    def test_onboarding_role_preset_and_history(self):
        old=content.read_categories()
        result=cm.profile({'role':'Frontend engineer','intervalHours':0,'applyStarter':True,'revision':cm.digest(old)})
        self.assertTrue(result['onboarded'])
        self.assertIn('accessibility',[c['id'] for c in result['categories']])
        self.assertEqual(result['history'][0]['categories'],old)
        self.assertEqual(db.read()['jiraTickets']['T-1']['categories'],[])

    def test_profile_only_preserves_categories(self):
        before=content.read_categories()
        cm.profile({'role':'Custom engineering role','intervalHours':168})
        self.assertEqual(content.read_categories(),before)
        self.assertEqual(cm.status()['intervalHours'],168)
        self.assertFalse(cm.status()['history'])

    def test_scan_is_review_only_and_reject_keeps_data(self):
        before=content.read_categories()
        review=self.scan([{'action':'rename','id':'bugs','name':'Defects','reason':'Clearer label'}])
        self.assertEqual(content.read_categories(),before)
        cm.decide(review['id'],{'decision':'reject','suggestionIds':[review['suggestions'][0]['suggestionId']]})
        self.assertEqual(content.read_categories(),before)
        self.assertFalse(cm.status()['history'])

    def test_merge_restores_tags_and_keeps_new_ticket_fields(self):
        review=self.scan([{'action':'merge','id':'bugs','targetId':'features','reason':'Same workflow'}])
        result=self.accept(review)
        target=content.read_categories()[0]
        self.assertEqual(set(target['docs']),{'bug-guide','feature-guide'})
        self.assertEqual(db.read()['jiraTickets']['T-1']['categories'],['features'])
        db.update_ticket('T-1', {'notes':[{'text':'new note'}],'jiraStatus':'Done'})
        db.update_ticket('T-3', {'summary':'Created later','categories':['features']})
        cm.restore(result['history'][0]['id'])
        ticket=db.read()['jiraTickets']['T-1']
        self.assertEqual(ticket['categories'],['bugs'])
        self.assertEqual(ticket['notes'],[{'text':'new note'}])
        self.assertEqual(ticket['codexSessionId'],'session')
        self.assertEqual(ticket['jiraStatus'],'Done')
        self.assertIn('T-3',db.read()['jiraTickets'])
        self.assertEqual(len(cm.status()['history']),2)

    def test_stale_title_or_categories_block_acceptance(self):
        review=self.scan([{'action':'rename','id':'bugs','name':'Defects','reason':'Clarity'}])
        db.update_ticket('T-1',{'summary':'Changed scope'})
        with self.assertRaisesRegex(ValueError,'changed since'):
            self.accept(review)
        self.assertEqual(content.read_categories()[0]['name'],'Bugs')

    def test_partial_decisions_remain_reviewable(self):
        review=self.scan([{'action':'rename','id':'bugs','name':'Defects','reason':'Clarity'},
                          {'action':'add','id':'testing','name':'Testing','reason':'Testing work','ticketKeys':['T-2']}])
        self.accept(review,[review['suggestions'][0]['suggestionId']])
        result=self.accept(review,[review['suggestions'][1]['suggestionId']])
        self.assertTrue(all(s['status']=='accepted' for s in result['reviews'][0]['suggestions']))
        self.assertEqual(db.read()['jiraTickets']['T-2']['categories'],['features','testing'])

    def test_conflicting_selected_suggestions_are_atomic(self):
        review=self.scan([{'action':'merge','id':'bugs','targetId':'features','reason':'Consolidate'},
                          {'action':'rename','id':'bugs','name':'Defects','reason':'Clarity'}])
        before=content.read_categories()
        with self.assertRaises(ValueError):self.accept(review)
        self.assertEqual(content.read_categories(),before)
        self.assertFalse(cm.status()['history'])

    def test_unknown_ids_and_invalid_model_output_are_rejected(self):
        cm.SCAN_LOCK.acquire()
        with patch.object(cm,'ask_llm',return_value={'suggestions':[{'action':'assign','reason':'bad','ticketKeys':['UNKNOWN'],'categoryIds':['bugs']}]}):cm.scan_worker()
        self.assertEqual(cm.status()['scan']['status'],'error')
        self.assertFalse(cm.status()['reviews'])

    def test_manual_stale_revision(self):
        with self.assertRaisesRegex(ValueError,'changed since'):
            cm.update_categories([category('new')], 'stale')
        self.assertFalse(cm.status()['history'])

    def test_interrupted_commit_recovers_from_journal(self):
        with patch.object(content,'write_categories',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):cm.update_categories([category('bugs')])
        self.assertIn('pendingCommit',cm.read_state())
        cm.status()
        self.assertNotIn('pendingCommit',cm.read_state())
        self.assertEqual([c['id'] for c in content.read_categories()],['bugs'])
        self.assertEqual(db.read()['jiraTickets']['T-2']['categories'],[])

    def test_schedule_is_opt_in_and_waits_for_pending_review(self):
        with patch.object(cm,'start_scan') as start:
            cm.maybe_scan();start.assert_not_called()
            cm.profile({'role':'Backend engineer','intervalHours':24})
            cm.maybe_scan();start.assert_called_once()
        self.scan([{'action':'rename','id':'bugs','name':'Defects','reason':'Clarity'}])
        with patch.object(cm,'start_scan') as start:
            cm.maybe_scan();start.assert_not_called()

    def test_prompt_excludes_ticket_bodies_and_notes(self):
        db.update_ticket('T-1',{'description':'PRIVATE BODY','notes':[{'text':'PRIVATE NOTE'}]})
        prompt=cm.review_prompt('Engineer',content.read_categories(),cm.ticket_input())
        self.assertIn('Fix login',prompt)
        self.assertNotIn('PRIVATE BODY',prompt)
        self.assertNotIn('PRIVATE NOTE',prompt)

if __name__=='__main__':unittest.main()
