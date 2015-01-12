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
Common functionalities shared between different DRAC modules.
"""

from oslo.utils import excutils
from oslo.utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.drivers.modules.drac import client as drac_client
from ironic.drivers.modules.drac import resource_uris
from ironic.openstack.common import log as logging

pywsman = importutils.try_import('pywsman')

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'drac_host': _('IP address or hostname of the DRAC card. Required.'),
    'drac_username': _('username used for authentication. Required.'),
    'drac_password': _('password used for authentication. Required.')
}
OPTIONAL_PROPERTIES = {
    'drac_port': _('port used for WS-Man endpoint; default is 443. Optional.'),
    'drac_path': _('path used for WS-Man endpoint; default is "/wsman". '
                   'Optional.'),
    'drac_protocol': _('protocol used for WS-Man endpoint; one of http, https;'
                       ' default is "https". Optional.'),
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)

# ReturnValue constants
RET_SUCCESS = '0'
RET_ERROR = '2'
RET_CREATED = '4096'


def parse_driver_info(node):
    """Parse a node's driver_info values.

    Parses the driver_info of the node, reads default values
    and returns a dict containing the combination of both.

    :param node: an ironic node object.
    :returns: a dict containing information from driver_info
              and default values.
    :raises: InvalidParameterValue if some mandatory information
             is missing on the node or on invalid inputs.
    """
    driver_info = node.driver_info
    parsed_driver_info = {}

    error_msgs = []
    for param in REQUIRED_PROPERTIES:
        try:
            parsed_driver_info[param] = str(driver_info[param])
        except KeyError:
            error_msgs.append(_("'%s' not supplied to DracDriver.") % param)
        except UnicodeEncodeError:
            error_msgs.append(_("'%s' contains non-ASCII symbol.") % param)

    parsed_driver_info['drac_port'] = driver_info.get('drac_port', 443)

    try:
        parsed_driver_info['drac_path'] = str(driver_info.get('drac_path',
                                                              '/wsman'))
    except UnicodeEncodeError:
        error_msgs.append(_("'drac_path' contains non-ASCII symbol."))

    try:
        parsed_driver_info['drac_protocol'] = str(
            driver_info.get('drac_protocol', 'https'))
    except UnicodeEncodeError:
        error_msgs.append(_("'drac_protocol' contains non-ASCII symbol."))

    try:
        parsed_driver_info['drac_port'] = int(parsed_driver_info['drac_port'])
    except ValueError:
        error_msgs.append(_("'drac_port' is not an integer value."))

    if error_msgs:
        msg = (_('The following errors were encountered while parsing '
                 'driver_info:\n%s') % '\n'.join(error_msgs))
        raise exception.InvalidParameterValue(msg)

    return parsed_driver_info


def get_wsman_client(node):
    """Return a DRAC client object.

    Given an ironic node object, this method gives back a
    Client object which is a wrapper for pywsman.Client.

    :param node: an ironic node object.
    :returns: a Client object.
    :raises: InvalidParameterValue if some mandatory information
             is missing on the node or on invalid inputs.
    """
    driver_info = parse_driver_info(node)
    client = drac_client.Client(**driver_info)
    return client


def find_xml(doc, item, namespace, find_all=False):
    """Find the first or all elements in a ElementTree object.

    :param doc: the element tree object.
    :param item: the element name.
    :param namespace: the namespace of the element.
    :param find_all: Boolean value, if True find all elements, if False
                     find only the first one. Defaults to False.
    :returns: if find_all is False the element object will be returned
              if found, None if not found. If find_all is True a list of
              element objects will be returned or an empty list if no
              elements were found.

    """
    query = ('.//{%(namespace)s}%(item)s' % {'namespace': namespace,
                                             'item': item})
    if find_all:
        return doc.findall(query)
    return doc.find(query)


def create_config_job(node):
    """Create a configuration job.

    This method is used to apply the pending values created by
    set_boot_device().

    :param node: an ironic node object.
    :raises: DracClientError on an error from pywsman library.
    :raises: DracConfigJobCreationError on an error when creating the job.

    """
    client = get_wsman_client(node)
    selectors = {'CreationClassName': 'DCIM_BIOSService',
                 'Name': 'DCIM:BIOSService',
                 'SystemCreationClassName': 'DCIM_ComputerSystem',
                 'SystemName': 'DCIM:ComputerSystem'}
    properties = {'Target': 'BIOS.Setup.1-1',
                  'ScheduledStartTime': 'TIME_NOW'}
    doc = client.wsman_invoke(resource_uris.DCIM_BIOSService,
                              'CreateTargetedConfigJob',
                              selectors,
                              properties)
    return_value = find_xml(doc, 'ReturnValue',
                            resource_uris.DCIM_BIOSService).text
    # NOTE(lucasagomes): Possible return values are: RET_ERROR for error
    #                    or RET_CREATED job created (but changes will be
    #                    applied after the reboot)
    # Boot Management Documentation: http://goo.gl/aEsvUH (Section 8.4)
    if return_value == RET_ERROR:
        error_message = find_xml(doc, 'Message',
                                 resource_uris.DCIM_BIOSService).text
        raise exception.DracConfigJobCreationError(error=error_message)


def check_for_config_job(node):
    """Check if a configuration job is already created.

    :param node: an ironic node object.
    :raises: DracClientError on an error from pywsman library.
    :raises: DracConfigJobCreationError if the job is already created.

    """
    client = get_wsman_client(node)
    try:
        doc = client.wsman_enumerate(resource_uris.DCIM_LifecycleJob)
    except exception.DracClientError as exc:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE('DRAC driver failed to list the configuration jobs '
                          'for node %(node_uuid)s. Reason: %(error)s.'),
                      {'node_uuid': node.uuid, 'error': exc})

    items = find_xml(doc, 'DCIM_LifecycleJob',
                     resource_uris.DCIM_LifecycleJob,
                     find_all=True)
    for i in items:
        name = find_xml(i, 'Name', resource_uris.DCIM_LifecycleJob)
        if 'BIOS.Setup.1-1' not in name.text:
            continue

        job_status = find_xml(i, 'JobStatus',
                              resource_uris.DCIM_LifecycleJob).text
        # If job is already completed or failed we can
        # create another one.
        # Job Control Documentation: http://goo.gl/o1dDD3 (Section 7.2.3.2)
        if job_status.lower() not in ('completed', 'failed'):
            job_id = find_xml(i, 'InstanceID',
                              resource_uris.DCIM_LifecycleJob).text
            reason = (_('Another job with ID "%s" is already created '
                        'to configure the BIOS. Wait until existing job '
                        'is completed or is cancelled') % job_id)
            raise exception.DracConfigJobCreationError(error=reason)
