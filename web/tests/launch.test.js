import test from 'node:test';
import assert from 'node:assert/strict';
import {launchCode} from '../src/api.js';

test('launchCode accepts only a well-formed #launch= fragment',()=>{
  assert.equal(launchCode('#launch=abcDEF0123456789_-xyz'),'abcDEF0123456789_-xyz');
  for(const bad of ['','#','#launch=','#launch=short','#launch=abc def0123456789xyz','#x=1&launch=abcDEF0123456789xyz',
    '#launch=abcDEF0123456789xyz&more','launch=abcDEF0123456789xyz',undefined,null])assert.equal(launchCode(bad),'',String(bad));
});
