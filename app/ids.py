import secrets
# no 0,O,1,l - unambiguous
ALPHABET = "23456789abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"


def new_id(prefix:str,lenght: int = 14) -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(lenght))
    return f"{prefix}_{body}"