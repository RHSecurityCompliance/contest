import re


def make_printable(obj):
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode()
    elif not isinstance(obj, str):
        obj = str(obj)
    obj = re.sub(r"\n\r", " ", obj)
    obj = re.sub(r"""[^\w\-\+~\.,:;!\?@#$%^&*=\(\)<>{}\[\]'"`/\\| ]""", "", obj, flags=re.ASCII)
    return obj.strip()
