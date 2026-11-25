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

class RemoveDeviceOwnership:
    def __init__(self):
        pass

    def __repr__(self):
        return f"RemoveDeviceOwnership()"
    
    def to_dict(self):
        return {
            "type": "RemoveDeviceOwnership",
            "input": None
        }