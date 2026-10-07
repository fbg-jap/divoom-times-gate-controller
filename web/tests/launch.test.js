import test from 'node:test';
import assert from 'node:assert/strict';
import {launchCode,cleanToken} from '../src/api.js';

test('launchCode accepts only a well-formed #launch= fragment',()=>{
  assert.equal(launchCode('#launch=abcDEF0123456789_-xyz'),'abcDEF0123456789_-xyz');
  for(const bad of ['','#','#launch=','#launch=short','#launch=abc def0123456789xyz','#x=1&launch=abcDEF0123456789xyz',
    '#launch=abcDEF0123456789xyz&more','launch=abcDEF0123456789xyz',undefined,null])assert.equal(launchCode(bad),'',String(bad));
});

test('cleanToken removes every kind of whitespace and tolerates non-strings',()=>{
  assert.equal(cleanToken('abc123_-XYZ'),'abc123_-XYZ');
  assert.equal(cleanToken('  abc123 \n'),'abc123');
  assert.equal(cleanToken('abc\r\n12\t3 4\u00a05'),'abc12345');
  assert.equal(cleanToken(''),'');
  assert.equal(cleanToken(undefined),'');
  assert.equal(cleanToken(null),'');
});
