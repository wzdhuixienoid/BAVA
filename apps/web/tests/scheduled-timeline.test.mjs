import assert from 'node:assert/strict';
import test from 'node:test';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import './tsx-loader.mjs';
const {WorkflowTimeline}=await import('../features/workflows/WorkflowTimeline.tsx');
const workflow={presentation:{stages:[{key:'submit',label:'提交执行',status:'WAITING_USER'},{key:'provider',label:'Provider 处理',status:'PENDING'}]}};
test('authorized schedule waits for time, immediate transfer still waits for user',()=>{
 const html=renderToStaticMarkup(createElement(WorkflowTimeline,{workflow,scheduleStatus:'SCHEDULED'}));
 assert.match(html,/到时自动执行/);assert.match(html,/等待执行时间/);assert.doesNotMatch(html,/等待用户操作/);
 const instant=renderToStaticMarkup(createElement(WorkflowTimeline,{workflow}));assert.match(instant,/等待用户操作/);assert.match(instant,/提交执行/);
});
