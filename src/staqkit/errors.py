class StaqkitError(Exception):
    pass


class ConfigError(StaqkitError):
    pass


class ValidationError(StaqkitError):
    pass


class AccessError(StaqkitError):
    pass
