import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from image_store import Store, FORMAT, atomic_json, digest, validate_bundle


def bundle(path, layers=(b'base', b'delta'), corrupt_layer=False):
    checks=[hashlib.sha256(x).hexdigest() for x in layers]
    config=json.dumps({'rootfs':{'diff_ids':['sha256:'+x for x in checks]}}).encode()
    identity=hashlib.sha256(config).hexdigest()
    config_name='blobs/sha256/'+identity
    entries={config_name:config}
    entries.update({'blobs/sha256/'+h:data for h,data in zip(checks,layers)})
    if corrupt_layer:
        entries['blobs/sha256/'+checks[0]]=b'wrong'
    entries['manifest.json']=json.dumps([{'Config':config_name,'Layers':['blobs/sha256/'+x for x in checks]}]).encode()
    with tarfile.open(path,'w:gz') as archive:
        for name,data in entries.items():
            entry=tarfile.TarInfo(name);entry.size=len(data)
            archive.addfile(entry,io.BytesIO(data))
    return 'sha256:'+identity


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.store=Store(self.root,lambda *a,**k:'',minimum_free=0,export=None)
        self.store.directory.mkdir(parents=True)
        p=self.store.directory/'temp.gz'
        self.image=bundle(p)
        h=digest(p);p.rename(self.store.directory/(h+'.tar.gz'))
        self.value={'format':FORMAT,'archive':h+'.tar.gz','sha256':h,
                    'bytes':p.with_name(h+'.tar.gz').stat().st_size,'images':[self.image]}
        self.store.commit(self.value)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_aliases_use_same_storage_and_validate_exact_layers(self):
        self.assertEqual(validate_bundle(self.store.archive_for(self.image),[self.image]),
                         {'images_verified':1,'layers_verified':2})
        alias=self.root/'images'/(self.image[7:]+'.tar')
        self.assertTrue(os.path.samefile(alias,self.store.archive_for(self.image)))

    def test_content_corruption_cannot_be_loaded(self):
        path=self.store.archive_for(self.image)
        data=bytearray(path.read_bytes());data[-9]^=1;path.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'checksum'):
            self.store.archive_for(self.image)

    def test_layers_cannot_change_under_same_image_identity(self):
        path=self.root/'bad.tar.gz'
        image=bundle(path,corrupt_layer=True)
        with self.assertRaisesRegex(ValueError,'digest'):
            validate_bundle(path,[image])

    def test_unexpected_image_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'exactly'):
            validate_bundle(self.store.archive_for(self.image),['sha256:'+'a'*64])

    def test_symlink_or_traversal_index_rejected(self):
        for name in ('../escape.tar.gz','/tmp/escape.tar.gz'):
            atomic_json(self.store.index,dict(self.value,archive=name))
            with self.assertRaisesRegex(ValueError,'name'):
                self.store.read()
        atomic_json(self.store.index,self.value)
        moved=self.store.index.with_name('actual.json');self.store.index.rename(moved)
        self.store.index.symlink_to(moved)
        with self.assertRaisesRegex(ValueError,'symlink'):
            self.store.read()

    def test_export_failure_preserves_previous_index_and_links(self):
        old=self.store.index.read_bytes()
        with patch.object(self.store,'load_missing'),patch.object(self.store,'create',return_value=self.value),\
             patch.object(self.store,'publish',side_effect=RuntimeError('encryption failed')):
            with self.assertRaises(RuntimeError):
                self.store.retain({'image':'sha256:'+'b'*64})
        self.assertEqual(old,self.store.index.read_bytes())
        self.store.archive_for(self.image)

    def test_missing_alias_can_be_repaired_without_new_export(self):
        alias=self.root/'images'/(self.image[7:]+'.tar');alias.unlink()
        with patch.object(self.store,'create',side_effect=AssertionError('unneeded export')):
            self.store.retain({'image':self.image})
        self.assertTrue(os.path.samefile(alias,self.store.archive_for(self.image)))

    def test_partial_link_failure_can_be_completed_without_losing_image(self):
        alias=self.root/'images'/(self.image[7:]+'.tar');alias.unlink()
        with patch('image_store.os.replace',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):self.store.link_images(self.value)
        self.store.archive_for(self.image)
        self.store.retain({'image':self.image})
        self.assertTrue(alias.exists())

    def test_cleanup_preserves_unrelated_files_and_referenced_generations(self):
        unrelated=self.store.directory/'important.tar.gz';unrelated.write_bytes(b'keep')
        linked=self.store.directory/('f'*64+'.tar.gz');linked.write_bytes(b'keep')
        os.link(linked,self.root/'reference')
        orphan=self.store.directory/('e'*64+'.tar.gz');orphan.write_bytes(b'remove')
        self.store.collect(self.value)
        self.assertTrue(unrelated.exists());self.assertTrue(linked.exists());self.assertFalse(orphan.exists())

    def test_missing_blob_blocks_retain_before_any_modification(self):
        path=self.store.archive_for(self.image);path.unlink()
        with patch.object(self.store,'create',side_effect=AssertionError('must not run')):
            with self.assertRaisesRegex(ValueError,'missing'):
                self.store.retain({'image':'sha256:'+'c'*64})


if __name__=='__main__': unittest.main()
