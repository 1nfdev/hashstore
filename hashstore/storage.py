import hashstore.local_store as localstore
import hashstore.udk as udk
import requests
import json
import six
from hashstore.utils import json_encoder
import logging
log = logging.getLogger(__name__)

methods_to_implement = ['store_directories', 'write_content', 'get_content']

class Storage:
    pass

class LocalStorage(Storage):
    def __init__(self, path):
        self.store = localstore.HashStore(path)

    def __getattr__(self, name):
        if name in methods_to_implement:
            return getattr(self.store, name)
        else:
            raise AttributeError('%s.%s is not delegated ' %
                                 (self.__class__.__name__, name) )


class RemoteStorage(Storage):
    def __init__(self, url):
        self.url = url
        self.headers = {}

    def set_auth_session(self,auth_session):
        self.headers['auth_session'] = str(auth_session)

    def register(self,mount_uuid, invitation=None, meta = None):
        response = self.post_meta_data('register',
                                   {'mount_uuid': mount_uuid,
                                    'invitation': invitation,
                                    'meta': meta})
        return json.loads(response)

    def login(self,mount_uuid):
        response = self.post_meta_data('login', {'mount_uuid': mount_uuid})
        return json.loads(response)

    def logout(self):
        return self.post_meta_data('logout', {})

    def store_directories(self,directories,mount_hash=None,auth_session=None):
        req = {
            'directories': {str(k): v for k,v in six.iteritems(directories)},
            'root': mount_hash
        }
        text = self.post_meta_data('store_directories', req)
        return json.loads(text)

    def post_meta_data(self, data_ptr, data):
        meta_url = self.url + '.hashery/' + data_ptr
        in_data = json_encoder.encode(data)
        r = requests.post(meta_url, headers=self.headers, data=in_data)
        out_data = r.text
        log.debug('post_meta_data:\n'
                  ' {meta_url}\n'
                  ' in: {in_data}\n'
                  ' out: {out_data}'.format(**locals()))
        return out_data

    def write_content(self,fp):
        r = requests.post(self.url+'.hashery/write_content', headers=self.headers, data=fp)
        text = r.text
        log.info(text)
        return udk.UDK.ensure_it(json.loads(r.text))

    def get_content(self,k):
        if k.has_data():
            return six.BytesIO(k.data())
        url = self.url + '.hashery/' + str(k.strip_bundle())
        return requests.get(url, headers=self.headers, stream=True).raw



def factory(config_dict):
    '''

    :param path_resolver:
    :param config_dict:
    :return: destination instance
    '''
    config_dict = dict(config_dict)
    constructor = globals()[config_dict['type'] + 'Storage']
    del config_dict['type']
    return constructor(**config_dict)
