import unittest

from abxr.device_policy import is_client_admin, parse_device_owner, parse_is_hms

DUMPSYS_OWNED_BY_CLIENT = """Current Device Policy Manager state:
  Immutable state:
    mHasFeature=true
  Device Owner: 
    admin=ComponentInfo{app.xrdm.client/app.xrdm.client.AdminReceiver}
    name=
    package=app.xrdm.client
  Enabled Device Admins (User 0, provisioningState: 3):
    app.xrdm.client/.AdminReceiver:
"""

DUMPSYS_OWNED_BY_OTHER_MDM = DUMPSYS_OWNED_BY_CLIENT.replace(
    "app.xrdm.client/app.xrdm.client.AdminReceiver", "com.managexr.agent/com.managexr.agent.AdminReceiver"
)

DUMPSYS_NO_OWNER = """Current Device Policy Manager state:
  Immutable state:
    mHasFeature=true
  Enabled Device Admins (User 0, provisioningState: 0):
"""


class DevicePolicyTest(unittest.TestCase):
    def test_reads_the_device_owner(self):
        self.assertEqual("app.xrdm.client/app.xrdm.client.AdminReceiver", parse_device_owner(DUMPSYS_OWNED_BY_CLIENT))
        self.assertIsNone(parse_device_owner(DUMPSYS_NO_OWNER))
        self.assertIsNone(parse_device_owner("Can't find service: device_policy"))

    def test_recognises_our_admin_receiver_in_both_forms(self):
        self.assertTrue(is_client_admin("app.xrdm.client/.AdminReceiver"))
        self.assertTrue(is_client_admin("app.xrdm.client/app.xrdm.client.AdminReceiver"))
        self.assertFalse(is_client_admin(parse_device_owner(DUMPSYS_OWNED_BY_OTHER_MDM)))
        self.assertFalse(is_client_admin(None))

    def test_reads_hms_from_the_oemconfig_provider(self):
        self.assertTrue(parse_is_hms("Row: 0 managed=1"))
        self.assertFalse(parse_is_hms("Row: 0 managed=-1"))
        self.assertFalse(parse_is_hms("Error while accessing provider:com.oculus.oemconfig.provider\njava.lang.IllegalArgumentException: Unknown URL ... not found"))


if __name__ == "__main__":
    unittest.main()
