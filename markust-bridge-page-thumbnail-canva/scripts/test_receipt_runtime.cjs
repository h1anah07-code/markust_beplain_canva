// Offline integration: safe persistence, baseline reuse, failure propagation, no clobber.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const cp = require('node:child_process');
const assert = require('node:assert/strict');
(async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'markust-receipt-'));
  try {
    const helper = new Function(fs.readFileSync(path.join(__dirname, 'receipt_runtime.js'), 'utf8') + '; return saveReceipt;')();
    const literal = "quote ' and $(touch NEVER_EXECUTE) `touch NEVER_EXECUTE` \\ backslash 한글 😀\n";
    const job = path.join(root, literal.replace(/\n/g, ' '));
    const before = {pages:[{page_id:'p',page_number:1,dimension:{width:1600,height:1600},is_editable:true}],richtexts:[],fills:[]};
    const baselinePath=path.join(root,'baseline.json');fs.writeFileSync(baselinePath,JSON.stringify(before));
    const result={...before,notes:literal.repeat(1600),edit_operation_results:[]};
    const tools={exec_command:async ({cmd}) => {
      const r=cp.spawnSync('/bin/sh',['-c',cmd],{cwd:root,encoding:'utf8',maxBuffer:2000000});
      return {exit_code:r.status,output:r.stdout+r.stderr};
    }};
    const args={tools,result,request:{operations:[]},baselinePath,jobDir:job,receiptId:'attempt1',skillDir:path.dirname(__dirname),python:process.env.PYTHON||'python3'};
    let out=await helper(args);assert.equal(out.exitCode,0);assert.deepEqual(JSON.parse(fs.readFileSync(out.paths.raw)),result);
    assert.equal(fs.statSync(out.paths.raw).mode&0o777,0o600);assert(!fs.existsSync(path.join(root,'NEVER_EXECUTE')));
    await assert.rejects(()=>helper(args),/persistence failed/);
    assert.deepEqual(JSON.parse(fs.readFileSync(out.paths.raw)),result);
    const changed=structuredClone(result);changed.pages[0].dimension.width=900;
    out=await helper({...args,result:changed,receiptId:'attempt2'});assert.equal(out.exitCode,1);assert(out.summary.pageStructureChanged);
    const failed={...before,edit_operation_results:[{status:'failure',message:'expired transaction'}]};
    out=await helper({...args,result:failed,request:{operations:[{type:'format_text',element_id:'missing'}]},receiptId:'attempt3'});
    assert.equal(out.exitCode,1);assert.equal(out.summary.acceptance.failureCount,1);
    assert.equal(out.summary.acceptance.missingOperationResultCount,0);assert.deepEqual(out.summary.missingTargetIds,['missing']);
    await assert.rejects(()=>helper({...args,receiptId:'attempt4',tools:{exec_command:async()=>({exit_code:1,output:'denied'})}}),/persistence failed/);
    console.log(JSON.stringify({passed:true,checks:['literal shell characters','unicode chunking','exact raw persistence','private permissions','no overwrite','baselinePath reuse','failure and missing target propagation','write failure stops']}));
  } finally {fs.rmSync(root,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
