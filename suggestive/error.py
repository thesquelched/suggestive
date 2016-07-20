class SuggestiveError(Exception):
    pass


class CommandError(SuggestiveError):

    def __init__(self, message):
        self.message = message
        super(CommandError, self).__init__(message)


class RetryError(SuggestiveError):
    """Used for retries"""
    pass
