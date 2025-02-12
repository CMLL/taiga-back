# Copyright (C) 2014 Andrey Antukh <niwi@niwi.be>
# Copyright (C) 2014 Jesús Espino <jespinog@gmail.com>
# Copyright (C) 2014 David Barragán <bameda@dbarragan.com>
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import uuid

from django.apps import apps
from django.db.models import Q, F
from django.utils.translation import ugettext as _
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.conf import settings

from taiga.base import exceptions as exc
from taiga.base import filters
from taiga.base import response
from taiga.auth.tokens import get_user_for_token
from taiga.base.decorators import list_route
from taiga.base.decorators import detail_route
from taiga.base.api import ModelCrudViewSet
from taiga.base.filters import PermissionBasedFilterBackend
from taiga.base.api.utils import get_object_or_404
from taiga.base.filters import MembersFilterBackend
from taiga.projects.votes import services as votes_service

from easy_thumbnails.source_generators import pil_image

from djmail.template_mail import MagicMailBuilder
from djmail.template_mail import InlineCSSTemplateMail

from . import models
from . import serializers
from . import permissions
from . import filters as user_filters
from . import services
from .signals import user_cancel_account as user_cancel_account_signal


class UsersViewSet(ModelCrudViewSet):
    permission_classes = (permissions.UserPermission,)
    admin_serializer_class = serializers.UserAdminSerializer
    serializer_class = serializers.UserSerializer
    queryset = models.User.objects.all().prefetch_related("memberships")
    filter_backends = (MembersFilterBackend,)

    def get_serializer_class(self):
        if self.action in ["partial_update", "update", "retrieve", "by_username"]:
            user = self.object
            if self.request.user == user or self.request.user.is_superuser:
                return self.admin_serializer_class

        return self.serializer_class

    def create(self, *args, **kwargs):
        raise exc.NotSupported()

    def list(self, request, *args, **kwargs):
        self.object_list = MembersFilterBackend().filter_queryset(request,
                                                                  self.get_queryset(),
                                                                  self)

        page = self.paginate_queryset(self.object_list)
        if page is not None:
            serializer = self.get_pagination_serializer(page)
        else:
            serializer = self.get_serializer(self.object_list, many=True)

        return response.Ok(serializer.data)

    @list_route(methods=["GET"])
    def by_username(self, request, *args, **kwargs):
        username = request.QUERY_PARAMS.get("username", None)
        return self.retrieve(request, username=username)

    def retrieve(self, request, *args, **kwargs):
        self.object = get_object_or_404(models.User, **kwargs)
        self.check_permissions(request, 'retrieve', self.object)
        serializer = self.get_serializer(self.object)
        return response.Ok(serializer.data)

    @detail_route(methods=["GET"])
    def contacts(self, request, *args, **kwargs):
        user = get_object_or_404(models.User, **kwargs)
        self.check_permissions(request, 'contacts', user)

        self.object_list = user_filters.ContactsFilterBackend().filter_queryset(
            user, request, self.get_queryset(), self).extra(
            select={"complete_user_name":"concat(full_name, username)"}).order_by("complete_user_name")

        page = self.paginate_queryset(self.object_list)
        if page is not None:
            serializer = self.serializer_class(page.object_list, many=True)
        else:
            serializer = self.serializer_class(self.object_list, many=True)

        return response.Ok(serializer.data)

    @detail_route(methods=["GET"])
    def stats(self, request, *args, **kwargs):
        user = get_object_or_404(models.User, **kwargs)
        self.check_permissions(request, "stats", user)
        return response.Ok(services.get_stats_for_user(user, request.user))

    @detail_route(methods=["GET"])
    def favourites(self, request, *args, **kwargs):
        for_user = get_object_or_404(models.User, **kwargs)
        from_user = request.user
        self.check_permissions(request, 'favourites', for_user)
        filters = {
            "type": request.GET.get("type", None),
            "action": request.GET.get("action", None),
            "q": request.GET.get("q", None),
        }

        self.object_list = services.get_favourites_list(for_user, from_user, **filters)
        page = self.paginate_queryset(self.object_list)

        extra_args = {
            "many": True,
            "user_votes": services.get_voted_content_for_user(request.user),
            "user_watching": services.get_watched_content_for_user(request.user),
        }

        if page is not None:
            serializer = serializers.FavouriteSerializer(page.object_list, **extra_args)
        else:
            serializer = serializers.FavouriteSerializer(self.object_list, **extra_args)

        return response.Ok(serializer.data)

    @list_route(methods=["POST"])
    def password_recovery(self, request, pk=None):
        username_or_email = request.DATA.get('username', None)

        self.check_permissions(request, "password_recovery", None)

        if not username_or_email:
            raise exc.WrongArguments(_("Invalid username or email"))

        try:
            queryset = models.User.objects.all()
            user = queryset.get(Q(username=username_or_email) |
                                    Q(email=username_or_email))
        except models.User.DoesNotExist:
            raise exc.WrongArguments(_("Invalid username or email"))

        user.token = str(uuid.uuid1())
        user.save(update_fields=["token"])

        mbuilder = MagicMailBuilder(template_mail_cls=InlineCSSTemplateMail)
        email = mbuilder.password_recovery(user, {"user": user})
        email.send()

        return response.Ok({"detail": _("Mail sended successful!")})

    @list_route(methods=["POST"])
    def change_password_from_recovery(self, request, pk=None):
        """
        Change password with token (from password recovery step).
        """

        self.check_permissions(request, "change_password_from_recovery", None)

        serializer = serializers.RecoverySerializer(data=request.DATA, many=False)
        if not serializer.is_valid():
            raise exc.WrongArguments(_("Token is invalid"))

        try:
            user = models.User.objects.get(token=serializer.data["token"])
        except models.User.DoesNotExist:
            raise exc.WrongArguments(_("Token is invalid"))

        user.set_password(serializer.data["password"])
        user.token = None
        user.save(update_fields=["password", "token"])

        return response.NoContent()

    @list_route(methods=["POST"])
    def change_password(self, request, pk=None):
        """
        Change password to current logged user.
        """
        self.check_permissions(request, "change_password", None)

        current_password = request.DATA.get("current_password")
        password = request.DATA.get("password")

        # NOTE: GitHub users have no password yet (request.user.passwor == '') so
        #       current_password can be None
        if not current_password and request.user.password:
            raise exc.WrongArguments(_("Current password parameter needed"))

        if not password:
            raise exc.WrongArguments(_("New password parameter needed"))

        if len(password) < 6:
            raise exc.WrongArguments(_("Invalid password length at least 6 charaters needed"))

        if current_password and not request.user.check_password(current_password):
            raise exc.WrongArguments(_("Invalid current password"))

        request.user.set_password(password)
        request.user.save(update_fields=["password"])
        return response.NoContent()

    @list_route(methods=["POST"])
    def change_avatar(self, request):
        """
        Change avatar to current logged user.
        """
        self.check_permissions(request, "change_avatar", None)

        avatar = request.FILES.get('avatar', None)

        if not avatar:
            raise exc.WrongArguments(_("Incomplete arguments"))

        try:
            pil_image(avatar)
        except Exception:
            raise exc.WrongArguments(_("Invalid image format"))

        request.user.delete_photo()
        request.user.photo = avatar
        request.user.save(update_fields=["photo"])
        user_data = self.admin_serializer_class(request.user).data

        return response.Ok(user_data)

    @list_route(methods=["POST"])
    def remove_avatar(self, request):
        """
        Remove the avatar of current logged user.
        """
        self.check_permissions(request, "remove_avatar", None)
        request.user.delete_photo()
        request.user.save(update_fields=["photo"])
        user_data = self.admin_serializer_class(request.user).data
        return response.Ok(user_data)

    #TODO: commit_on_success
    def partial_update(self, request, *args, **kwargs):
        """
        We must detect if the user is trying to change his email so we can
        save that value and generate a token that allows him to validate it in
        the new email account
        """
        user = self.get_object()
        self.check_permissions(request, "update", user)

        ret = super(UsersViewSet, self).partial_update(request, *args, **kwargs)

        new_email = request.DATA.get('email', None)
        if new_email is not None:
            valid_new_email = True
            duplicated_email = models.User.objects.filter(email = new_email).exists()

            try:
                validate_email(new_email)
            except ValidationError:
                valid_new_email = False

            valid_new_email = valid_new_email and new_email != request.user.email

            if duplicated_email:
                raise exc.WrongArguments(_("Duplicated email"))
            elif not valid_new_email:
                raise exc.WrongArguments(_("Not valid email"))

            #We need to generate a token for the email
            request.user.email_token = str(uuid.uuid1())
            request.user.new_email = new_email
            request.user.save(update_fields=["email_token", "new_email"])
            mbuilder = MagicMailBuilder(template_mail_cls=InlineCSSTemplateMail)
            email = mbuilder.change_email(request.user.new_email, {"user": request.user,
                                                                   "lang": request.user.lang})
            email.send()

        return ret

    @list_route(methods=["POST"])
    def change_email(self, request, pk=None):
        """
        Verify the email change to current logged user.
        """
        serializer = serializers.ChangeEmailSerializer(data=request.DATA, many=False)
        if not serializer.is_valid():
            raise exc.WrongArguments(_("Invalid, are you sure the token is correct and you "
                                       "didn't use it before?"))

        try:
            user = models.User.objects.get(email_token=serializer.data["email_token"])
        except models.User.DoesNotExist:
            raise exc.WrongArguments(_("Invalid, are you sure the token is correct and you "
                                       "didn't use it before?"))

        self.check_permissions(request, "change_email", user)
        user.email = user.new_email
        user.new_email = None
        user.email_token = None
        user.save(update_fields=["email", "new_email", "email_token"])

        return response.NoContent()

    @list_route(methods=["GET"])
    def me(self, request, pk=None):
        """
        Get me.
        """
        self.check_permissions(request, "me", None)
        user_data = self.admin_serializer_class(request.user).data
        return response.Ok(user_data)

    @list_route(methods=["POST"])
    def cancel(self, request, pk=None):
        """
        Cancel an account via token
        """
        serializer = serializers.CancelAccountSerializer(data=request.DATA, many=False)
        if not serializer.is_valid():
            raise exc.WrongArguments(_("Invalid, are you sure the token is correct?"))

        try:
            max_age_cancel_account = getattr(settings, "MAX_AGE_CANCEL_ACCOUNT", None)
            user = get_user_for_token(serializer.data["cancel_token"], "cancel_account",
                max_age=max_age_cancel_account)

        except exc.NotAuthenticated:
            raise exc.WrongArguments(_("Invalid, are you sure the token is correct?"))

        if not user.is_active:
            raise exc.WrongArguments(_("Invalid, are you sure the token is correct?"))

        user.cancel()
        return response.NoContent()

    def destroy(self, request, pk=None):
        user = self.get_object()
        self.check_permissions(request, "destroy", user)
        stream = request.stream
        request_data = stream is not None and stream.GET or None
        user_cancel_account_signal.send(sender=user.__class__, user=user, request_data=request_data)
        user.cancel()
        return response.NoContent()


######################################################
## Role
######################################################

class RolesViewSet(ModelCrudViewSet):
    model = models.Role
    serializer_class = serializers.RoleSerializer
    permission_classes = (permissions.RolesPermission, )
    filter_backends = (filters.CanViewProjectFilterBackend,)
    filter_fields = ('project',)

    def pre_delete(self, obj):
        move_to = self.request.QUERY_PARAMS.get('moveTo', None)
        if move_to:
            membership_model = apps.get_model("projects", "Membership")
            role_dest = get_object_or_404(self.model, project=obj.project, id=move_to)
            qs = membership_model.objects.filter(project_id=obj.project.pk, role=obj)
            qs.update(role=role_dest)

        super().pre_delete(obj)
