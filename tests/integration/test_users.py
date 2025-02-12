import pytest
from tempfile import NamedTemporaryFile

from django.contrib.contenttypes.models import ContentType
from django.core.urlresolvers import reverse
from django.core.files import File

from .. import factories as f

from taiga.base.utils import json
from taiga.users import models
from taiga.users.serializers import FavouriteSerializer
from taiga.auth.tokens import get_token_for_user
from taiga.permissions.permissions import MEMBERS_PERMISSIONS, ANON_PERMISSIONS, USER_PERMISSIONS
from taiga.users.services import get_favourites_list

from easy_thumbnails.files import generate_all_aliases, get_thumbnailer

import os

pytestmark = pytest.mark.django_db


def test_users_create_through_standard_api(client):
    user = f.UserFactory.create(is_superuser=True)

    url = reverse('users-list')
    data = {}

    response = client.post(url, json.dumps(data), content_type="application/json")
    assert response.status_code == 405

    client.login(user)

    response = client.post(url, json.dumps(data), content_type="application/json")
    assert response.status_code == 405


def test_update_user_with_same_email(client):
    user = f.UserFactory.create(email="same@email.com")
    url = reverse('users-detail', kwargs={"pk": user.pk})
    data = {"email": "same@email.com"}

    client.login(user)
    response = client.patch(url, json.dumps(data), content_type="application/json")

    assert response.status_code == 400
    assert response.data['_error_message'] == 'Duplicated email'


def test_update_user_with_duplicated_email(client):
    f.UserFactory.create(email="one@email.com")
    user = f.UserFactory.create(email="two@email.com")
    url = reverse('users-detail', kwargs={"pk": user.pk})
    data = {"email": "one@email.com"}

    client.login(user)
    response = client.patch(url, json.dumps(data), content_type="application/json")

    assert response.status_code == 400
    assert response.data['_error_message'] == 'Duplicated email'


def test_update_user_with_invalid_email(client):
    user = f.UserFactory.create(email="my@email.com")
    url = reverse('users-detail', kwargs={"pk": user.pk})
    data = {"email": "my@email"}

    client.login(user)
    response = client.patch(url, json.dumps(data), content_type="application/json")

    assert response.status_code == 400
    assert response.data['_error_message'] == 'Not valid email'


def test_update_user_with_valid_email(client):
    user = f.UserFactory.create(email="old@email.com")
    url = reverse('users-detail', kwargs={"pk": user.pk})
    data = {"email": "new@email.com"}

    client.login(user)
    response = client.patch(url, json.dumps(data), content_type="application/json")

    assert response.status_code == 200
    user = models.User.objects.get(pk=user.id)
    assert user.email_token is not None
    assert user.new_email == "new@email.com"


def test_validate_requested_email_change(client):
    user = f.UserFactory.create(email_token="change_email_token", new_email="new@email.com")
    url = reverse('users-change-email')
    data = {"email_token": "change_email_token"}

    client.login(user)
    response = client.post(url, json.dumps(data), content_type="application/json")

    assert response.status_code == 204
    user = models.User.objects.get(pk=user.id)
    assert user.email_token is None
    assert user.new_email is None
    assert user.email == "new@email.com"

def test_validate_requested_email_change_for_anonymous_user(client):
    user = f.UserFactory.create(email_token="change_email_token", new_email="new@email.com")
    url = reverse('users-change-email')
    data = {"email_token": "change_email_token"}

    response = client.post(url, json.dumps(data), content_type="application/json")

    assert response.status_code == 204
    user = models.User.objects.get(pk=user.id)
    assert user.email_token is None
    assert user.new_email is None
    assert user.email == "new@email.com"

def test_validate_requested_email_change_without_token(client):
    user = f.UserFactory.create(email_token="change_email_token", new_email="new@email.com")
    url = reverse('users-change-email')
    data = {}

    client.login(user)
    response = client.post(url, json.dumps(data), content_type="application/json")
    assert response.status_code == 400


def test_validate_requested_email_change_with_invalid_token(client):
    user = f.UserFactory.create(email_token="change_email_token", new_email="new@email.com")
    url = reverse('users-change-email')
    data = {"email_token": "invalid_email_token"}

    client.login(user)
    response = client.post(url, json.dumps(data), content_type="application/json")

    assert response.status_code == 400


def test_delete_self_user(client):
    user = f.UserFactory.create()
    url = reverse('users-detail', kwargs={"pk": user.pk})

    client.login(user)
    response = client.delete(url)

    assert response.status_code == 204
    user = models.User.objects.get(pk=user.id)
    assert user.full_name == "Deleted user"


def test_cancel_self_user_with_valid_token(client):
    user = f.UserFactory.create()
    url = reverse('users-cancel')
    cancel_token = get_token_for_user(user, "cancel_account")
    data = {"cancel_token": cancel_token}
    client.login(user)
    response = client.post(url, json.dumps(data), content_type="application/json")

    assert response.status_code == 204
    user = models.User.objects.get(pk=user.id)
    assert user.full_name == "Deleted user"


def test_cancel_self_user_with_invalid_token(client):
    user = f.UserFactory.create()
    url = reverse('users-cancel')
    data = {"cancel_token": "invalid_cancel_token"}
    client.login(user)
    response = client.post(url, json.dumps(data), content_type="application/json")

    assert response.status_code == 400


DUMMY_BMP_DATA = b'BM:\x00\x00\x00\x00\x00\x00\x006\x00\x00\x00(\x00\x00\x00\x01\x00\x00\x00\x01\x00\x00\x00\x01\x00\x18\x00\x00\x00\x00\x00\x04\x00\x00\x00\x13\x0b\x00\x00\x13\x0b\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'


def test_change_avatar(client):
    url = reverse('users-change-avatar')

    user = f.UserFactory()
    client.login(user)

    with NamedTemporaryFile() as avatar:
        # Test no avatar send
        post_data = {}
        response = client.post(url, post_data)
        assert response.status_code == 400

        # Test invalid file send
        post_data = {
            'avatar': avatar
        }
        response = client.post(url, post_data)
        assert response.status_code == 400

        # Test empty valid avatar send
        avatar.write(DUMMY_BMP_DATA)
        avatar.seek(0)
        response = client.post(url, post_data)
        assert response.status_code == 200


def test_change_avatar_removes_the_old_one(client):
    url = reverse('users-change-avatar')
    user = f.UserFactory()

    with NamedTemporaryFile(delete=False) as avatar:
        avatar.write(DUMMY_BMP_DATA)
        avatar.seek(0)
        user.photo = File(avatar)
        user.save()
        generate_all_aliases(user.photo, include_global=True)

    with NamedTemporaryFile(delete=False) as avatar:
        thumbnailer = get_thumbnailer(user.photo)
        original_photo_paths = [user.photo.path]
        original_photo_paths += [th.path for th in thumbnailer.get_thumbnails()]
        assert list(map(os.path.exists, original_photo_paths)) == [True, True, True, True]

        client.login(user)
        avatar.write(DUMMY_BMP_DATA)
        avatar.seek(0)
        post_data = {'avatar': avatar}
        response = client.post(url, post_data)

        assert response.status_code == 200
        assert list(map(os.path.exists, original_photo_paths)) == [False, False, False, False]


def test_remove_avatar(client):
    url = reverse('users-remove-avatar')
    user = f.UserFactory()

    with NamedTemporaryFile(delete=False) as avatar:
        avatar.write(DUMMY_BMP_DATA)
        avatar.seek(0)
        user.photo = File(avatar)
        user.save()
        generate_all_aliases(user.photo, include_global=True)

    thumbnailer = get_thumbnailer(user.photo)
    original_photo_paths = [user.photo.path]
    original_photo_paths += [th.path for th in thumbnailer.get_thumbnails()]
    assert list(map(os.path.exists, original_photo_paths)) == [True, True, True, True]

    client.login(user)
    response = client.post(url)

    assert response.status_code == 200
    assert list(map(os.path.exists, original_photo_paths)) == [False, False, False, False]


def test_list_contacts_private_projects(client):
    project = f.ProjectFactory.create()
    user_1 = f.UserFactory.create()
    user_2 = f.UserFactory.create()
    role = f.RoleFactory(project=project, permissions=["view_project"])
    membership_1 = f.MembershipFactory.create(project=project, user=user_1, role=role)
    membership_2 = f.MembershipFactory.create(project=project, user=user_2, role=role)

    url = reverse('users-contacts', kwargs={"pk": user_1.pk})
    response = client.get(url, content_type="application/json")
    assert response.status_code == 200
    response_content = response.data
    assert len(response_content) == 0

    client.login(user_1)
    response = client.get(url, content_type="application/json")
    assert response.status_code == 200
    response_content = response.data
    assert len(response_content) == 1
    assert response_content[0]["id"] == user_2.id


def test_list_contacts_no_projects(client):
    user_1 = f.UserFactory.create()
    user_2 = f.UserFactory.create()
    role_1 = f.RoleFactory(permissions=["view_project"])
    role_2 = f.RoleFactory(permissions=["view_project"])
    membership_1 = f.MembershipFactory.create(project=role_1.project, user=user_1, role=role_1)
    membership_2 = f.MembershipFactory.create(project=role_2.project, user=user_2, role=role_2)

    client.login(user_1)

    url = reverse('users-contacts', kwargs={"pk": user_1.pk})
    response = client.get(url, content_type="application/json")
    assert response.status_code == 200

    response_content = response.data
    assert len(response_content) == 0


def test_list_contacts_public_projects(client):
    project = f.ProjectFactory.create(is_private=False,
            anon_permissions=list(map(lambda x: x[0], ANON_PERMISSIONS)),
            public_permissions=list(map(lambda x: x[0], USER_PERMISSIONS)))

    user_1 = f.UserFactory.create()
    user_2 = f.UserFactory.create()
    role = f.RoleFactory(project=project)
    membership_1 = f.MembershipFactory.create(project=project, user=user_1, role=role)
    membership_2 = f.MembershipFactory.create(project=project, user=user_2, role=role)

    url = reverse('users-contacts', kwargs={"pk": user_1.pk})
    response = client.get(url, content_type="application/json")
    assert response.status_code == 200

    response_content = response.data
    assert len(response_content) == 1
    assert response_content[0]["id"] == user_2.id


def test_mail_permissions(client):
    user_1 = f.UserFactory.create(is_superuser=True)
    user_2 = f.UserFactory.create()

    url1 = reverse('users-detail', kwargs={"pk": user_1.pk})
    url2 = reverse('users-detail', kwargs={"pk": user_2.pk})

    # Anonymous user
    response = client.json.get(url1)
    assert response.status_code == 200
    assert "email" not in response.data

    response = client.json.get(url2)
    assert response.status_code == 200
    assert "email" not in response.data

    # Superuser
    client.login(user_1)

    response = client.json.get(url1)
    assert response.status_code == 200
    assert "email" in response.data

    response = client.json.get(url2)
    assert response.status_code == 200
    assert "email" in response.data

    # Normal user
    client.login(user_2)

    response = client.json.get(url1)
    assert response.status_code == 200
    assert "email" not in response.data

    response = client.json.get(url2)
    assert response.status_code == 200
    assert "email" in response.data


def test_get_favourites_list():
    fav_user = f.UserFactory()
    viewer_user = f.UserFactory()

    project = f.ProjectFactory(is_private=False, name="Testing project")
    role = f.RoleFactory(project=project, permissions=["view_project", "view_us", "view_tasks", "view_issues"])
    membership = f.MembershipFactory(project=project, role=role, user=fav_user)
    project.add_watcher(fav_user)
    content_type = ContentType.objects.get_for_model(project)
    f.VoteFactory(content_type=content_type, object_id=project.id, user=fav_user)
    f.VotesFactory(content_type=content_type, object_id=project.id, count=1)

    user_story = f.UserStoryFactory(project=project, subject="Testing user story")
    user_story.add_watcher(fav_user)
    content_type = ContentType.objects.get_for_model(user_story)
    f.VoteFactory(content_type=content_type, object_id=user_story.id, user=fav_user)
    f.VotesFactory(content_type=content_type, object_id=user_story.id, count=1)

    task = f.TaskFactory(project=project, subject="Testing task")
    task.add_watcher(fav_user)
    content_type = ContentType.objects.get_for_model(task)
    f.VoteFactory(content_type=content_type, object_id=task.id, user=fav_user)
    f.VotesFactory(content_type=content_type, object_id=task.id, count=1)

    issue = f.IssueFactory(project=project, subject="Testing issue")
    issue.add_watcher(fav_user)
    content_type = ContentType.objects.get_for_model(issue)
    f.VoteFactory(content_type=content_type, object_id=issue.id, user=fav_user)
    f.VotesFactory(content_type=content_type, object_id=issue.id, count=1)

    assert len(get_favourites_list(fav_user, viewer_user)) == 8
    assert len(get_favourites_list(fav_user, viewer_user, type="project")) == 2
    assert len(get_favourites_list(fav_user, viewer_user, type="userstory")) == 2
    assert len(get_favourites_list(fav_user, viewer_user, type="task")) == 2
    assert len(get_favourites_list(fav_user, viewer_user, type="issue")) == 2
    assert len(get_favourites_list(fav_user, viewer_user, type="unknown")) == 0

    assert len(get_favourites_list(fav_user, viewer_user, action="watch")) == 4
    assert len(get_favourites_list(fav_user, viewer_user, action="vote")) == 4

    assert len(get_favourites_list(fav_user, viewer_user, q="issue")) == 2
    assert len(get_favourites_list(fav_user, viewer_user, q="unexisting text")) == 0


def test_get_favourites_list_valid_info_for_project():
    fav_user = f.UserFactory()
    viewer_user = f.UserFactory()
    watcher_user = f.UserFactory()

    project = f.ProjectFactory(is_private=False, name="Testing project", tags=['test', 'tag'])
    project.add_watcher(watcher_user)
    content_type = ContentType.objects.get_for_model(project)
    vote = f.VoteFactory(content_type=content_type, object_id=project.id, user=fav_user)
    f.VotesFactory(content_type=content_type, object_id=project.id, count=1)

    raw_project_vote_info = get_favourites_list(fav_user, viewer_user)[0]
    project_vote_info = FavouriteSerializer(raw_project_vote_info).data

    assert project_vote_info["type"] == "project"
    assert project_vote_info["action"] == "vote"
    assert project_vote_info["id"] == project.id
    assert project_vote_info["ref"] == None
    assert project_vote_info["slug"] == project.slug
    assert project_vote_info["name"] == project.name
    assert project_vote_info["subject"] == None
    assert project_vote_info["description"] == project.description
    assert project_vote_info["assigned_to"] == None
    assert project_vote_info["status"] == None
    assert project_vote_info["status_color"] == None

    tags_colors = {tc["name"]:tc["color"] for tc in project_vote_info["tags_colors"]}
    assert "test" in tags_colors
    assert "tag" in tags_colors

    assert project_vote_info["is_private"] == project.is_private
    assert project_vote_info["is_voted"] == False
    assert project_vote_info["is_watched"] == False
    assert project_vote_info["total_watchers"] == 1
    assert project_vote_info["total_votes"] == 1
    assert project_vote_info["project"] == None
    assert project_vote_info["project_name"] == None
    assert project_vote_info["project_slug"] == None
    assert project_vote_info["project_is_private"] == None
    assert project_vote_info["assigned_to_username"] == None
    assert project_vote_info["assigned_to_full_name"] == None
    assert project_vote_info["assigned_to_photo"] == None


def test_get_favourites_list_valid_info_for_not_project_types():
    fav_user = f.UserFactory()
    viewer_user = f.UserFactory()
    watcher_user = f.UserFactory()
    assigned_to_user = f.UserFactory()

    project = f.ProjectFactory(is_private=False, name="Testing project")

    factories = {
        "userstory": f.UserStoryFactory,
        "task": f.TaskFactory,
        "issue": f.IssueFactory
    }

    for object_type in factories:
        instance = factories[object_type](project=project,
            subject="Testing",
            tags=["test1", "test2"],
            assigned_to=assigned_to_user)

        instance.add_watcher(watcher_user)
        content_type = ContentType.objects.get_for_model(instance)
        vote = f.VoteFactory(content_type=content_type, object_id=instance.id, user=fav_user)
        f.VotesFactory(content_type=content_type, object_id=instance.id, count=3)

        raw_instance_vote_info = get_favourites_list(fav_user, viewer_user, type=object_type)[0]
        instance_vote_info = FavouriteSerializer(raw_instance_vote_info).data

        assert instance_vote_info["type"] == object_type
        assert instance_vote_info["action"] == "vote"
        assert instance_vote_info["id"] == instance.id
        assert instance_vote_info["ref"] == instance.ref
        assert instance_vote_info["slug"] == None
        assert instance_vote_info["name"] == None
        assert instance_vote_info["subject"] == instance.subject
        assert instance_vote_info["description"] == None
        assert instance_vote_info["assigned_to"] == instance.assigned_to.id
        assert instance_vote_info["status"] == instance.status.name
        assert instance_vote_info["status_color"] == instance.status.color

        tags_colors = {tc["name"]:tc["color"] for tc in instance_vote_info["tags_colors"]}
        assert "test1" in tags_colors
        assert "test2" in tags_colors

        assert instance_vote_info["is_private"] == None
        assert instance_vote_info["is_voted"] == False
        assert instance_vote_info["is_watched"] == False
        assert instance_vote_info["total_watchers"] == 1
        assert instance_vote_info["total_votes"] == 3
        assert instance_vote_info["project"] == instance.project.id
        assert instance_vote_info["project_name"] == instance.project.name
        assert instance_vote_info["project_slug"] == instance.project.slug
        assert instance_vote_info["project_is_private"] == instance.project.is_private
        assert instance_vote_info["assigned_to_username"] == instance.assigned_to.username
        assert instance_vote_info["assigned_to_full_name"] == instance.assigned_to.full_name
        assert instance_vote_info["assigned_to_photo"] != ""


def test_get_favourites_list_permissions():
    fav_user = f.UserFactory()
    viewer_unpriviliged_user = f.UserFactory()
    viewer_priviliged_user = f.UserFactory()

    project = f.ProjectFactory(is_private=True, name="Testing project")
    role = f.RoleFactory(project=project, permissions=["view_project", "view_us", "view_tasks", "view_issues"])
    membership = f.MembershipFactory(project=project, role=role, user=viewer_priviliged_user)
    content_type = ContentType.objects.get_for_model(project)
    f.VoteFactory(content_type=content_type, object_id=project.id, user=fav_user)
    f.VotesFactory(content_type=content_type, object_id=project.id, count=1)

    user_story = f.UserStoryFactory(project=project, subject="Testing user story")
    content_type = ContentType.objects.get_for_model(user_story)
    f.VoteFactory(content_type=content_type, object_id=user_story.id, user=fav_user)
    f.VotesFactory(content_type=content_type, object_id=user_story.id, count=1)

    task = f.TaskFactory(project=project, subject="Testing task")
    content_type = ContentType.objects.get_for_model(task)
    f.VoteFactory(content_type=content_type, object_id=task.id, user=fav_user)
    f.VotesFactory(content_type=content_type, object_id=task.id, count=1)

    issue = f.IssueFactory(project=project, subject="Testing issue")
    content_type = ContentType.objects.get_for_model(issue)
    f.VoteFactory(content_type=content_type, object_id=issue.id, user=fav_user)
    f.VotesFactory(content_type=content_type, object_id=issue.id, count=1)

    #If the project is private a viewer user without any permission shouldn' see
    # any vote
    assert len(get_favourites_list(fav_user, viewer_unpriviliged_user)) == 0

    #If the project is private but the viewer user has permissions the votes should
    # be accesible
    assert len(get_favourites_list(fav_user, viewer_priviliged_user)) == 4

    #If the project is private but has the required anon permissions the votes should
    # be accesible by any user too
    project.anon_permissions = ["view_project", "view_us", "view_tasks", "view_issues"]
    project.save()
    assert len(get_favourites_list(fav_user, viewer_unpriviliged_user)) == 4
