class WipeClient:
    def __init__(self):
        pass

    def __repr__(self):
        return f"WipeClient()"

    def to_dict(self):
        return {
            "type": "WipeClient",
            "input": {}
        }


class BootstrapViaJsonFile:
    def __init__(self, file_location):
        self.file_location = file_location

    def __repr__(self):
        return f"BootstrapViaJsonFile(file_location={self.file_location})"

    def to_dict(self):
        return {
            "type": "BootstrapViaJsonFile",
            "input": {
                "file": self.file_location
            }
        }
