"""Arayüzün kullanıcının diline çevirdiği iletiler. Metinler app/static/i18n içindedir."""


def message(key, **params):
    return {"key": key, "params": params}


class Problem(Exception):
    def __init__(self, key, **params):
        super().__init__(key)
        self.message = message(key, **params)
