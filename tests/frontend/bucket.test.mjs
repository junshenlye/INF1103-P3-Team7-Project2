import test from 'node:test';
import assert from 'node:assert/strict';
import {ModuleBucket,configureInputLimits} from '../../frontend/static/input-workspace.js';
const limits={document_bytes:1000,request_bytes:4000,module_count:2,documents_per_module:2,module_title_length:30,project_name_length:30,week_count:20,credit:10,media_types:['image/png']};
configureInputLimits(limits);
test('editing and cancelling preserve original File references and submission metadata',()=>{
 const bucket=new ModuleBucket(); const file=new File(['png'],'source.png',{type:'image/png'});
 bucket.name='Trimester'; bucket.weekCount='18'; bucket.current.title='Module'; bucket.addFiles([file]); bucket.save();
 bucket.edit(1); bucket.current.files=[]; bucket.cancel(); assert.equal(bucket.entries[0].files[0],file);
 const sent=bucket.submission(); const modules=JSON.parse(sent.upload.get('modules'));
 assert.equal(modules[0].file_fields[0],'module_0_file_0'); assert.equal(sent.upload.get('module_0_file_0').name,'source.png');
 assert.equal(bucket.entries[0].files[0],file);
 bucket.edit(1); bucket.current.credit='11'; assert.throws(()=>bucket.save(),/credits/); bucket.cancel();
 bucket.weekCount='21'; assert.throws(()=>bucket.submission(),/week count/);
});
test('undo cannot bypass server module count',()=>{
 const bucket=new ModuleBucket();
 const add=name=>{bucket.current.title=name;bucket.addFiles([new File(['png'],name+'.png',{type:'image/png'})]);bucket.save();};
 add('A');bucket.edit(1);bucket.remove();add('B');add('C');assert.throws(()=>bucket.undo(),/Remove a module/);
});

test('incomplete upload settings are rejected before showing the upload form',()=>{
 const stale={module_count:20,document_count:20,document_bytes:10485760,request_bytes:20971520};
 assert.throws(()=>configureInputLimits(stale),/Upload settings could not be loaded/);
 for(const media_types of [undefined,null,'image/png',[],[null]]) {
  assert.throws(()=>configureInputLimits({...limits,media_types}),/Upload settings could not be loaded/);
 }
 assert.throws(()=>configureInputLimits({...limits,documents_per_module:0}),/Upload settings could not be loaded/);
 configureInputLimits(limits);
 const bucket=new ModuleBucket();
 bucket.addFiles([new File(['png'],'source.png',{type:'image/png'})]);
 assert.equal(bucket.current.files.length,1);
 assert.throws(()=>bucket.addFiles([new File(['pdf'],'source.pdf',{type:'application/pdf'})]),/Choose PDF/,'Server restrictions remain enforced');
});
