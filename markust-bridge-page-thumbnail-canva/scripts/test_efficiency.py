import copy
import json
from pathlib import Path
import tempfile
import unittest

import canva_adapter as adapter
import copy_only as editor
import job_state


def state():
    return {'transaction': {'transaction_id': 'tx'}, 'pages': [
        {'page_id': 'page1', 'page_number': 1, 'dimension': {'width': 1600, 'height': 1600}, 'is_editable': True},
        {'page_id': 'page2', 'page_number': 2, 'dimension': {'width': 1600, 'height': 1600}, 'is_editable': True}],
        'richtexts': [
            {'element_id': 'text1', 'page_index': 1, 'regions': [{'type': 'character', 'text': 'Heading'}, {'type': 'character', 'text': '\nSupport.'}], 'containerElement': {'type': 'TEXT', 'position': {'left': 60, 'top': 300}, 'dimension': {'width': 700, 'height': 100}}},
            {'element_id': 'arrow', 'page_index': 2, 'regions': [], 'containerElement': {'type': 'SHAPE', 'position': {'left': 700, 'top': 500}, 'dimension': {'width': 100, 'height': 100}}}],
        'fills': [{'element_id': 'photo', 'page_index': 1, 'asset_id': 'asset', 'containerElement': {'type': 'SHAPE', 'position': {'left': 800, 'top': 300}, 'dimension': {'width': 700, 'height': 900}}}]}


def backup(baseline):
    clone = copy.deepcopy(baseline)
    for p in clone['pages']: p['page_id'] += '-copy'
    for e in clone['richtexts'] + clone['fills']: e['element_id'] += '-copy'
    return {'sourceDesign': {'id': 'source', 'page_count': 2}, 'backupDesign': {'id': 'backup', 'page_count': 2},
            'sourceReadback': baseline, 'backupReadback': clone}


class NativeRevisionTests(unittest.TestCase):
    def compile_copy(self, current=None, design=None, evidence=None):
        current = current or state()
        design = design or {'mode': 'copy-only', 'preservation': 'whole-design-backup', 'pages': [{'id': 'one', 'edits': [{'id': 'lead', 'find': 'Support.', 'replace': 'Concrete support.'}]}]}
        return editor.compile_plan(design, current, {'pages': {'one': 'page1'}, 'elements': {'lead': 'text1'}}, 'account', 'tx', [], backup_evidence=evidence or backup(current))

    def test_empty_shape_preserved_and_not_editable(self):
        plan = self.compile_copy()
        self.assertEqual(plan['expected']['richtexts'][1], state()['richtexts'][1])
        self.assertEqual(len(plan['requests'][0]['arguments']['operations']), 1)

    def test_mixed_style_exact_substitution(self):
        plan = self.compile_copy()
        self.assertEqual(plan['expected']['richtexts'][0]['regions'][0], state()['richtexts'][0]['regions'][0])
        self.assertTrue(editor.verify_plan(plan, plan['expected'])['passed'])
        self.assertEqual(plan['requests'][0]['arguments']['operations'][0]['type'], 'find_and_replace_text')

    def test_wrong_page(self):
        with self.assertRaisesRegex(ValueError, 'belong'):
            editor.compile_plan({'mode': 'copy-only', 'pages': [{'id': 'one', 'edits': [{'id': 'lead', 'find': 'Heading', 'replace': 'New'}]}]}, state(), {'pages': {'one': 'page2'}, 'elements': {'lead': 'text1'}}, 'account', 'tx', [1])

    def test_protected_and_ambiguous_text_blocked(self):
        with self.assertRaisesRegex(ValueError, 'protected'):
            editor.compile_plan({'mode': 'copy-only', 'pages': [{'id': 'one', 'edits': [{'id': 'lead', 'find': 'Heading', 'replace': 'New'}]}]}, state(), {'pages': {'one': 'page1'}, 'elements': {'lead': 'text1'}}, 'account', 'tx', [1])
        d=state();d['richtexts'][0]['regions'][1]['text']='Support. Support.'
        with self.assertRaisesRegex(ValueError, 'exactly once'): self.compile_copy(d)

    def test_backup_failure(self):
        d=state(); b=backup(d); b['backupReadback']['fills'][0]['asset_id']='wrong'
        with self.assertRaisesRegex(ValueError, 'preserve'): self.compile_copy(d,evidence=b)

    def test_stale_transaction(self):
        d=state();d['transaction']['transaction_id']='stale'
        with self.assertRaisesRegex(ValueError, 'transaction'): self.compile_copy(d)

    def test_graphic_mutation_detected(self):
        plan=self.compile_copy(); after=copy.deepcopy(plan['expected']);after['richtexts'][1]['containerElement']['position']['left']=0
        self.assertFalse(editor.verify_plan(plan,after)['passed'])

    def addition(self):
        baseline=state();current=copy.deepcopy(baseline)
        n=copy.deepcopy(baseline['richtexts'][0]);n.update(element_id='newtext',regions=[{'type':'character','text':'Added support.'}]);current['richtexts'].append(n)
        design={'mode':'copy-add','preservation':'whole-design-backup','pages':[{'id':'one','additions':[{'id':'new','text':'Added support.','box':{'x':60,'y':1200,'width':1400},'formatting':{'font_size':42,'color':'#5B5D66'}}]}]}
        mapping={'pages':{'one':'page1'},'elements':{'new':'newtext'}}
        return baseline,current,design,mapping

    def test_add_only_new_text_and_verify(self):
        b,c,d,m=self.addition();p=editor.compile_plan(d,c,m,'account','tx',[],baseline_readback=b,backup_evidence=backup(b))
        ops=p['requests'][0]['arguments']['operations'];self.assertEqual(len(ops),4);self.assertEqual({o['element_id'] for o in ops},{'newtext'})
        after=copy.deepcopy(p['expected']);after['richtexts'][-1]['containerElement']['dimension']={'width':1400,'height':140}
        self.assertTrue(editor.verify_plan(p,after)['passed'])
        after['richtexts'][-1]['containerElement']['dimension']['width']=100
        self.assertFalse(editor.verify_plan(p,after)['passed'])

    def test_wrong_insertion_and_mutation_blocked(self):
        b,c,d,m=self.addition();c['richtexts'][-1]['page_index']=2
        with self.assertRaisesRegex(ValueError, 'wrong page'): editor.compile_plan(d,c,m,'account','tx',[],baseline_readback=b,backup_evidence=backup(b))
        b,c,d,m=self.addition();c['fills'][0]['asset_id']='changed'
        with self.assertRaisesRegex(ValueError, 'changed'): editor.compile_plan(d,c,m,'account','tx',[],baseline_readback=b,backup_evidence=backup(b))

    def test_new_text_cannot_be_disguised_as_existing_edit(self):
        b,c,d,m=self.addition();d['pages'][0]['edits']=[{'id':'disguised','find':'Added','replace':'New'}];m['elements']['disguised']='newtext'
        with self.assertRaisesRegex(ValueError, 'baseline element'): editor.compile_plan(d,c,m,'account','tx',[],baseline_readback=b,backup_evidence=backup(b))

    def test_resume_start_receipt(self):
        d=state();current=copy.deepcopy(d);del current['transaction']
        p=editor.compile_plan({'mode':'copy-only','pages':[{'id':'one','edits':[{'id':'lead','find':'Heading','replace':'New'}]}]},current,{'pages':{'one':'page1'},'elements':{'lead':'text1'}},'account','tx',[2],transaction_readback=d)
        self.assertTrue(p['readyToSend'])


class ReceiptTests(unittest.TestCase):
    def test_failure_missing_unknown_counts_preserved(self):
        for results in [[{'status':'success'},{'status':'failure','message':'bad'}],[{'status':'success'}],[{'status':'unknown'},{'status':'success'}]]:
            raw={**state(),'edit_operation_results':results}
            request={'operations':[{'type':'replace_text','element_id':'text1','text':'Heading\nSupport.'}]*2}
            out=adapter.compact_receipt(raw,request)
            self.assertEqual(out['acceptance'],adapter.summarize_receipt(raw,2));self.assertFalse(out['acceptance']['allAppliedConfirmed'])

    def test_top_error_and_unexpected_state(self):
        raw={**state(),'isError':True,'error':{'message':'expired'}}
        out=adapter.compact_receipt(raw,{'operations':[]});self.assertTrue(out['errors']);self.assertTrue(out['acceptance']['topLevelError'])
        before=state();after=copy.deepcopy(before);after['fills'][0]['asset_id']='wrong'
        out=adapter.compact_receipt(after,{'operations':[]},before);self.assertEqual(out['unexpectedChangedIds'],['photo'])

    def test_success_receipt_does_not_hide_wrong_properties_or_pages(self):
        before=state();raw=copy.deepcopy(before);raw['edit_operation_results']=[{'status':'success'}]
        req={'operations':[{'type':'replace_text','element_id':'text1','text':'Different'}]}
        out=adapter.compact_receipt(raw,req,before)
        self.assertTrue(out['acceptance']['allAppliedConfirmed']);self.assertEqual(len(out['propertyChecks']['failed']),1)
        raw['pages'][0]['dimension']['width']=900
        self.assertTrue(adapter.compact_receipt(raw,req,before)['pageStructureChanged'])

    def test_insertion_wrong_page_and_bad_baseline_are_visible(self):
        before=state();raw=copy.deepcopy(before);new=copy.deepcopy(raw['fills'][0]);new.update(element_id='new',page_index=2);raw['fills'].append(new)
        req={'operations':[{'type':'insert_fill','page_id':'page1','asset_id':'a'}]}
        out=adapter.compact_receipt(raw,req,before)
        self.assertEqual(out['unexpectedAddedIds'],['new']);self.assertIn('inspectionRequired',out)
        self.assertIn('inspectionRequired',adapter.compact_receipt(raw,req,{'partial':True}))


class ReuseTests(unittest.TestCase):
    def test_dependency_reuse_and_targeted_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for f in ['video','transcript','photo','layout']: (root/f).write_text(f)
            spec={'stages':[{'id':'analysis','files':['video']},{'id':'photos','dependsOn':['analysis'],'params':{'age':27}},{'id':'layout','dependsOn':['photos']}]};ledger={}
            for sid,out in [('analysis','transcript'),('photos','photo'),('layout','layout')]: job_state.record(spec,ledger,root,sid,[out],'passed')
            self.assertEqual(job_state.plan(spec,ledger,root)['runCount'],0)
            spec['stages'][1]['params']['age']=45
            self.assertEqual([r['action'] for r in job_state.plan(spec,ledger,root)['stages']],['reuse','run','run'])

    def test_failed_or_modified_output_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'out').write_text('a');spec={'stages':[{'id':'one'}]};ledger={}
            job_state.record(spec,ledger,root,'one',['out'],'failed');self.assertEqual(job_state.plan(spec,ledger,root)['runCount'],1)
            job_state.record(spec,ledger,root,'one',['out'],'passed');(root/'out').write_text('changed');self.assertEqual(job_state.plan(spec,ledger,root)['runCount'],1)


if __name__ == '__main__': unittest.main()
