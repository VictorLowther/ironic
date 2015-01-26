#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
DRAC VendorPassthruBios Driver
"""

from ironic.drivers import base
from ironic.drivers.modules.drac import bios
from ironic.drivers.modules.drac import common as drac_common


class DracVendorPassthru(base.VendorInterface):
    """Interface for DRAC specific BIOS configuration methods."""

    def get_properties(self):
        return {}

    def validate(self, task, **kwargs):
        return drac_common.parse_driver_info(task.node)

    @base.passthru(['GET'], method='get_bios_config', async=False)
    def get_bios_config(self, task, **kwargs):
        return bios.get_config(task.node)

    @base.passthru(['POST'], method='set_bios_config', async=False)
    def set_bios_config(self, task, **kwargs):
        return bios.set_config(task.node, **kwargs)

    @base.passthru(['POST'], method='commit_bios_config')
    def commit_bios_config(self, task, **kwargs):
        return bios.commit_config(task.node)

    @base.passthru(['DELETE'], method='abandon_bios_config', async=False)
    def abandon_bios_config(self, task, **kwargs):
        return bios.abandon_config(task.node)
