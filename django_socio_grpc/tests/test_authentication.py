import json
import logging
from unittest import mock

from django.test import TestCase, override_settings
from grpc._cython.cygrpc import _Metadatum

from django_socio_grpc.services import Service
from django_socio_grpc.services.servicer_proxy import get_servicer_context
from django_socio_grpc.settings import grpc_settings
from django_socio_grpc.tests.grpc_test_utils.fake_grpc import FakeContext

logger = logging.getLogger()


class FakeAuthentication:
    def authenticate(self, context):
        return ({"email": "john.doe@johndoe.com"}, context.META.get("HTTP_AUTHORIZATION"))


class DummyService(Service):
    def DummyMethod(service, request, context):
        pass


class TestAuthenticationUnitary(TestCase):
    @override_settings(
        GRPC_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": [
                "django_socio_grpc.tests.test_authentication.FakeAuthentication",
            ],
        }
    )
    def test_settings(self):
        # test settings correctly passed to grpc_settings
        self.assertEqual(grpc_settings.DEFAULT_AUTHENTICATION_CLASSES, [FakeAuthentication])

    def test_perform_authentication(self):
        #   Create a dummyservice for unitary tests
        dummy_service = DummyService()
        dummy_service.context = FakeContext()
        #   Call func
        with mock.patch(
            "django_socio_grpc.services.Service.resolve_user"
        ) as mock_resolve_user:
            mock_resolve_user.return_value = ({"email": "john.doe@johndoe.com"}, {})
            dummy_service.perform_authentication()
            mock_resolve_user.assert_called_once_with()

        self.assertEqual(dummy_service.context.user, {"email": "john.doe@johndoe.com"})
        self.assertEqual(dummy_service.context.auth, {})

    def test_resolve_user(self):
        dummy_service = DummyService()
        dummy_service.context = FakeContext()
        dummy_service.context.META = {"HTTP_AUTHORIZATION": "faketoken"}
        dummy_service.authentication_classes = [FakeAuthentication]

        auth_user_tuple = dummy_service.resolve_user()
        self.assertEqual(auth_user_tuple, ({"email": "john.doe@johndoe.com"}, "faketoken"))

    @mock.patch("django_socio_grpc.services.Service.check_permissions", mock.MagicMock())
    def test_perform_authentication_called_in_before_action(self):
        dummy_service = DummyService()
        with mock.patch(
            "django_socio_grpc.services.Service.perform_authentication"
        ) as mock_perform_authentication:
            dummy_service.before_action()
            mock_perform_authentication.assert_called_once_with()


class TestAuthenticationIntegration(TestCase):
    def setUp(self):
        self.servicer = DummyService.as_servicer()

        self.fake_context = FakeContext()

    def test_user_and_token_none_if_no_auth_class(self):
        self.servicer.DummyMethod(None, self.fake_context)

        servicer_context = get_servicer_context()
        self.assertIsNone(servicer_context.service.context.user)
        self.assertIsNone(servicer_context.service.context.auth)

    def test_user_and_token_set(self):
        DummyService.authentication_classes = [FakeAuthentication]
        metadata = (("headers", json.dumps({"Authorization": "faketoken"})),)
        self.fake_context._invocation_metadata.extend((_Metadatum(k, v) for k, v in metadata))
        self.servicer.DummyMethod(None, self.fake_context)

        servicer_context = get_servicer_context()

        self.assertEqual(
            servicer_context.service.context.META, {"HTTP_AUTHORIZATION": "faketoken"}
        )
        self.assertEqual(
            servicer_context.service.context.user, {"email": "john.doe@johndoe.com"}
        )
        self.assertEqual(servicer_context.service.context.auth, "faketoken")
