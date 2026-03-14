from storages.backends.s3 import S3Storage


class CKEditorPublicStorage(S3Storage):
    """
    Storage backend for CKEditor uploads with stable public URLs.
    """
    location = ''
    default_acl = None
    file_overwrite = False
    querystring_auth = False
