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
DRAC Bios specific methods
"""

from oslo.utils import excutils
from oslo.utils import importutils

from ironic.common import exception
from ironic.common.i18n import _LE
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import management
from ironic.drivers.modules.drac import resource_uris
from ironic.openstack.common import log as logging

pywsman = importutils.try_import('pywsman')

LOG = logging.getLogger(__name__)

NAMESPACES = [
    "http://schemas.dell.com/wbem/wscim/1/cim-schema/2/DCIM_BIOSEnumeration",
    "http://schemas.dell.com/wbem/wscim/1/cim-schema/2/DCIM_BIOSString",
    "http://schemas.dell.com/wbem/wscim/1/cim-schema/2/DCIM_BIOSInteger"]


def get_config(node):
    res = {}
    client = drac_common.get_wsman_client(node)
    for namespace in NAMESPACES:
        try:
            doc = client.wsman_enumerate(namespace)
        except exception.DracClientError as exc:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('DRAC driver failed to get BIOS settings '
                              'for node %(node_uuid)s. '
                              'Reason: %(error)s.'),
                          {'node_uuid': node.uuid, 'error': exc})
        items = drac_common.find_xml(doc, 'Items', namespace)
        for item in items:
            name = item.find(None, "AttributeName").text()
            if name == None:
                raise exception.DracOperationError(
                    operation="get BIOS setting",
                    message='Item has no name: "%s"' % item.to_xml())
            res[name] = {}
            res[name]['current_value'] = item.find(None, "CurrentValue").text()
            res[name]['read_only'] = item.find(None,
                                               "IsReadOnly").text() == "true"
            if res[name]['read_only']:
                continue
            # pending_value is a little special, because it can either have
            # a nil attribute or some innter text.
            pending_value = item.find(None, "PendingValue")
            pvnil = pending_value.attr_find(None, "nil")

            if pvnil != None and pvnil.value() == "true":
                res[name]['pending_value'] = None
            else:
                res[name]['pending_value'] = pending_value.text()

            # Next, do namespace-specific things.
            # This includes getting information about what is and
            # is not a valid value to pass pack to the caller.
            if item.name() == 'DCIM_BIOSEnumeration':
                possible_values = []
                pv = item.findall(None, "PossibleValues")
                for v in pv:
                    possible_values.append(v.text())
                res[name]['possible_values'] = possible_values
            elif item.name() == 'DCIM_BIOSString':
                res[name]['min_length'] = int(item.find(None, "MinLength"))
                res[name]['max_length'] = int(item.find(None, "MaxLength"))
                res[name]['pcre_regex'] = item.find(None, "ValueExpression")
            elif item.name() == 'DCIM_BIOSInteger':
                res[name]['lower_bound'] = int(item.find(None, "LowerBound"))
                res[name]['upper_bound'] = int(item.find(None, "UpperBound"))
            else:
                raise exception.DracOperationError(
                    operation="get BIOS setting",
                    message='Unexpected DCIM item type "%s"' % item.name())
    return res


@task_manager.require_exclusive_lock
def set_config(node, **kwargs):
    management.check_for_config_job(node)
    current = get_config(node)
    unknown_keys = set(kwargs.keys()) - set(current.keys())
    if len(unknown_keys) > 0:
        raise exception.DracOperationError(
            operation="set BIOS settings",
            message='Unexpected BIOS attributes "%s"' % unknown_keys)

    read_only_keys = []
    attrib_names = []

    for k in kwargs:
        if current[k]['read_only']:
            read_only_keys.append(k)
        elif (kwargs[k]['pending_value'] != None and
              kwargs[k]['pending_value'] != current[k]['current_value']):
            attrib_names.append(k)

    if len(read_only_keys) > 0:
        raise exception.DracOperationError(
            operation="set BIOS settings",
            message='Cannot set read-only BIOS settings "%s"' % read_only_keys)

    attrib_vals = []
    for n in attrib_names:
        attrib_vals.append(kwargs[n]['pending_value'])

    client = drac_common.get_wsman_client(node)
    selectors = {'CreationClassName': 'DCIM_BIOSService',
                 'Name': 'DCIM:BIOSService',
                 'SystemCreationClassName': 'DCIM_ComputerSystem',
                 'SystemName': 'DCIM:ComputerSystem'}
    properties = {'Target': 'BIOS.Setup-1.1',
                  'AttributeName': attrib_names,
                  'AttribValue': attrib_vals}
    doc = client.wsman_invoke(resource_uris.DCIM_BIOSService,
                              'SetAttributes',
                              selectors,
                              properties)
    return_value = doc.find(None, 'ReturnValue').text()
    if return_value == drac_common.RET_ERROR:
        error_messages = doc.find_all(None, 'Message')
        error_parameters = doc.find_all(None, 'MessageArguments')
        expanded_messages = map(
            lambda pair: pair[0].text() % pair[1].text(),
            zip(error_messages, error_parameters))
        raise exception.DracOperationError(operation='set_bios_settings',
                                           error=expanded_messages)
    set_results = doc.find_all(None, 'RebootRequired')
    return any(map(lambda res: res.text() == 'Yes', set_results))


@task_manager.require_exclusive_lock
def commit_config(node):
    management.check_for_config_job(node)
    management.create_config_job(node)


@task_manager.require_exclusive_lock
def abandon_config(node):
    client = drac_common.get_wsman_client(node)
    selectors = {'CreationClassName': 'DCIM_BIOSService',
                 'Name': 'DCIM:BIOSService',
                 'SystemCreationClassName': 'DCIM_ComputerSystem',
                 'SystemName': 'DCIM:ComputerSystem'}
    properties = {'Target': 'BIOS.Setup-1.1'}

    doc = client.wsman_invoke(resource_uris.DCIM_BIOSService,
                              'DeletePendingConfiguration',
                              selectors,
                              properties)

    return_value = doc.find(None, 'ReturnValue').text()
    message = doc.find(None, 'Message').text()

    if return_value != drac_common.RET_SUCCESS:
        raise exception.DracOperationError(operation='abandon_config',
                                           error=message)

    LOG.debug('DRAC driver abandon_config(%(node_uuid)s): %(message)s',
              {'node_uuid': node.uuid, 'message': message})
