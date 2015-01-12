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
Test class for common methods used by DRAC modules.
"""

import mock

from xml.etree import ElementTree

from testtools.matchers import HasLength

from ironic.common import exception
from ironic.drivers.modules.drac import client as drac_client
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import resource_uris
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.drivers.drac import utils as test_utils
from ironic.tests.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_drac_info()


class DracCommonMethodsTestCase(db_base.DbTestCase):

    def test_parse_driver_info(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        info = drac_common.parse_driver_info(node)

        self.assertIsNotNone(info.get('drac_host'))
        self.assertIsNotNone(info.get('drac_port'))
        self.assertIsNotNone(info.get('drac_path'))
        self.assertIsNotNone(info.get('drac_protocol'))
        self.assertIsNotNone(info.get('drac_username'))
        self.assertIsNotNone(info.get('drac_password'))

    def test_parse_driver_info_missing_host(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_host']
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_parse_driver_info_missing_port(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_port']

        info = drac_common.parse_driver_info(node)
        self.assertEqual(443, info.get('drac_port'))

    def test_parse_driver_info_invalid_port(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        node.driver_info['drac_port'] = 'foo'
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_parse_driver_info_missing_path(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_path']

        info = drac_common.parse_driver_info(node)
        self.assertEqual('/wsman', info.get('drac_path'))

    def test_parse_driver_info_missing_protocol(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_protocol']

        info = drac_common.parse_driver_info(node)
        self.assertEqual('https', info.get('drac_protocol'))

    def test_parse_driver_info_missing_username(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_username']
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_parse_driver_info_missing_password(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_password']
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_find_xml(self):
        namespace = 'http://fake'
        value = 'fake_value'
        test_doc = ElementTree.fromstring("""<Envelope xmlns:ns1="%(ns)s">
                         <Body>
                           <ns1:test_element>%(value)s</ns1:test_element>
                         </Body>
                       </Envelope>""" % {'ns': namespace, 'value': value})

        result = drac_common.find_xml(test_doc, 'test_element', namespace)
        self.assertEqual(value, result.text)

    def test_find_xml_find_all(self):
        namespace = 'http://fake'
        value1 = 'fake_value1'
        value2 = 'fake_value2'
        test_doc = ElementTree.fromstring("""<Envelope xmlns:ns1="%(ns)s">
                         <Body>
                           <ns1:test_element>%(value1)s</ns1:test_element>
                           <ns1:cat>meow</ns1:cat>
                           <ns1:test_element>%(value2)s</ns1:test_element>
                           <ns1:dog>bark</ns1:dog>
                         </Body>
                       </Envelope>""" % {'ns': namespace, 'value1': value1,
                                         'value2': value2})

        result = drac_common.find_xml(test_doc, 'test_element',
                                      namespace, find_all=True)
        self.assertThat(result, HasLength(2))
        result_text = [v.text for v in result]
        self.assertEqual(sorted([value1, value2]), sorted(result_text))


@mock.patch.object(drac_client, 'pywsman')
class DracCommonWsmanMethodsCase(db_base.DbTestCase):

    def setUp(self):
        super(DracCommonWsmanMethodsCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)

    def test_check_for_config_job(self, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'DCIM_LifecycleJob':
                                                    {'Name': 'fake'}}],
                                          resource_uris.DCIM_LifecycleJob)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.enumerate.return_value = mock_xml

        result = drac_common.check_for_config_job(self.node)

        self.assertIsNone(result)
        mock_pywsman.enumerate.assert_called_once_with(mock.ANY, mock.ANY,
            resource_uris.DCIM_LifecycleJob)

    def test_check_for_config_job_already_exist(self, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'DCIM_LifecycleJob':
                                                    {'Name': 'BIOS.Setup.1-1',
                                                     'JobStatus': 'scheduled',
                                                     'InstanceID': 'fake'}}],
                                          resource_uris.DCIM_LifecycleJob)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.enumerate.return_value = mock_xml

        self.assertRaises(exception.DracConfigJobCreationError,
                          drac_common.check_for_config_job, self.node)
        mock_pywsman.enumerate.assert_called_once_with(mock.ANY, mock.ANY,
            resource_uris.DCIM_LifecycleJob)

    def test_create_config_job(self, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'ReturnValue':
                                                    drac_common.RET_SUCCESS}],
                                               resource_uris.DCIM_BIOSService)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.invoke.return_value = mock_xml

        result = drac_common.create_config_job(self.node)

        self.assertIsNone(result)
        mock_pywsman.invoke.assert_called_once_with(mock.ANY,
            resource_uris.DCIM_BIOSService, 'CreateTargetedConfigJob', None)

    def test_create_config_job_error(self, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'ReturnValue':
                                                    drac_common.RET_ERROR,
                                                 'Message': 'E_FAKE'}],
                                               resource_uris.DCIM_BIOSService)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.invoke.return_value = mock_xml

        self.assertRaises(exception.DracConfigJobCreationError,
                          drac_common.create_config_job, self.node)
        mock_pywsman.invoke.assert_called_once_with(mock.ANY,
            resource_uris.DCIM_BIOSService, 'CreateTargetedConfigJob', None)
