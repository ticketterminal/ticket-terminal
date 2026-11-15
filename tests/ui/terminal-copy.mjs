import {parseHTML} from 'linkedom';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('../..',import.meta.url));
const {window,document}=parseHTML('<html><body><div class="termhost" id="host"></div></body></html>');
const copied=[];

class FakeTerminal {
  constructor(){ this.rows=24; this.cols=80; this.selection=''; FakeTerminal.latest=this; }
  loadAddon(){}
  open(container){ container.appendChild(document.createElement('div')); }
  onData(callback){ this.dataHandler=callback; }
  onSelectionChange(callback){ this.selectionHandler=callback; }
  attachCustomKeyEventHandler(callback){ this.keyHandler=callback; }
  getSelection(){ return this.selection; }
  hasSelection(){ return Boolean(this.selection); }
  setSelection(value){ this.selection=value; this.selectionHandler(); }
  write(){}
  focus(){}
  dispose(){}
}
class FakeWebSocket {
  static OPEN=1;
  constructor(){ this.readyState=FakeWebSocket.OPEN; }
  addEventListener(){}
  send(){}
  close(){}
}
class FakeResizeObserver { observe(){} disconnect(){} }

Object.assign(globalThis,{
  window,document,
  location:{protocol:'http:',host:'localhost:4173'},
  Terminal:FakeTerminal,
  FitAddon:{FitAddon:class {fit(){}}},
  WebSocket:FakeWebSocket,
  ResizeObserver:FakeResizeObserver,
});
Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:async text=>copied.push(text)}}});

await import(root+'/public/terminal.js');
const host=document.getElementById('host');
window.openTicketTerminal(host,'OPS-1','work on it',{provider:'claude'});
const term=FakeTerminal.latest;
const button=host.querySelector('.terminal-copy-button');

assert(button,'terminal includes an explicit copy-selection control');
assert.equal(button.hidden,true,'copy control stays out of the way without a selection');
term.setSelection('first line\nsecond line');
assert.equal(button.hidden,false,'selecting terminal output reveals the copy control');

button.click();
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(copied.at(-1),'first line\nsecond line','copy button writes the exact xterm selection');
assert.equal(button.textContent,'Copied','copy button confirms success');

assert.equal(term.keyHandler({type:'keydown',key:'c',metaKey:true,ctrlKey:false,shiftKey:false}),false,'Cmd+C is handled as copy');
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(copied.at(-1),'first line\nsecond line');
assert.equal(term.keyHandler({type:'keydown',key:'c',metaKey:false,ctrlKey:true,shiftKey:false}),false,'Ctrl+C copies when text is selected');

term.setSelection('');
assert.equal(button.hidden,true);
assert.equal(term.keyHandler({type:'keydown',key:'c',metaKey:false,ctrlKey:true,shiftKey:false}),true,'Ctrl+C still reaches the PTY as interrupt without a selection');
assert.equal(term.keyHandler({type:'keydown',key:'c',metaKey:false,ctrlKey:true,shiftKey:true}),false,'Ctrl+Shift+C remains a copy-only shortcut');

console.log('terminal-copy.mjs OK');
