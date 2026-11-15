"""JWT sign-in that also applies the access policy, on every API request.

DRF runs a view's authentication before anything else, and every view uses
it - unlike permission classes, which a view replaces wholesale when it sets
its own. So this is the one place a rule can't be skipped by a view that
forgot it:

* an account whose access has ended (``access_expires_on``) is signed out;
* the route's required capability (``access.required_capability``) is
  checked against the person's role, and the request refused if it's missing.

Views keep their finer checks on top. A refusal is still logged by
``AuditContextMiddleware``, which is handed the person here because DRF
clears the signed-in user when authentication raises.
"""
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

from . import access


class AccessPolicyAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        if user.access_expired:
            raise AuthenticationFailed("Your access has ended. Ask the owner to extend it.", code="access_ended")
        need = access.required_capability(request.path, request.method)
        if not access.allowed(user, need):
            # Who was refused, for the activity log (DRF is about to forget).
            request._request.refused_user = user
            raise PermissionDenied(access.refusal(need))
        return user, token
