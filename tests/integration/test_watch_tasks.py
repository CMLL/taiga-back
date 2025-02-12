# Copyright (C) 2015 Andrey Antukh <niwi@niwi.be>
# Copyright (C) 2015 Jesús Espino <jespinog@gmail.com>
# Copyright (C) 2015 David Barragán <bameda@dbarragan.com>
# Copyright (C) 2015 Anler Hernández <hello@anler.me>
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

import pytest
import json
from django.core.urlresolvers import reverse

from .. import factories as f

pytestmark = pytest.mark.django_db


def test_watch_task(client):
    user = f.UserFactory.create()
    task = f.create_task(owner=user)
    f.MembershipFactory.create(project=task.project, user=user, is_owner=True)
    url = reverse("tasks-watch", args=(task.id,))

    client.login(user)
    response = client.post(url)

    assert response.status_code == 200


def test_unwatch_task(client):
    user = f.UserFactory.create()
    task = f.create_task(owner=user)
    f.MembershipFactory.create(project=task.project, user=user, is_owner=True)
    url = reverse("tasks-watch", args=(task.id,))

    client.login(user)
    response = client.post(url)

    assert response.status_code == 200


def test_list_task_watchers(client):
    user = f.UserFactory.create()
    task = f.TaskFactory(owner=user)
    f.MembershipFactory.create(project=task.project, user=user, is_owner=True)
    f.WatchedFactory.create(content_object=task, user=user)
    url = reverse("task-watchers-list", args=(task.id,))

    client.login(user)
    response = client.get(url)

    assert response.status_code == 200
    assert response.data[0]['id'] == user.id


def test_get_task_watcher(client):
    user = f.UserFactory.create()
    task = f.TaskFactory(owner=user)
    f.MembershipFactory.create(project=task.project, user=user, is_owner=True)
    watch = f.WatchedFactory.create(content_object=task, user=user)
    url = reverse("task-watchers-detail", args=(task.id, watch.user.id))

    client.login(user)
    response = client.get(url)

    assert response.status_code == 200
    assert response.data['id'] == watch.user.id


def test_get_task_watchers(client):
    user = f.UserFactory.create()
    task = f.TaskFactory(owner=user)
    f.MembershipFactory.create(project=task.project, user=user, is_owner=True)
    url = reverse("tasks-detail", args=(task.id,))

    f.WatchedFactory.create(content_object=task, user=user)

    client.login(user)
    response = client.get(url)

    assert response.status_code == 200
    assert response.data['watchers'] == [user.id]


def test_get_task_is_watched(client):
    user = f.UserFactory.create()
    task = f.TaskFactory(owner=user)
    f.MembershipFactory.create(project=task.project, user=user, is_owner=True)
    url_detail = reverse("tasks-detail", args=(task.id,))
    url_watch = reverse("tasks-watch", args=(task.id,))
    url_unwatch = reverse("tasks-unwatch", args=(task.id,))

    client.login(user)

    response = client.get(url_detail)
    assert response.status_code == 200
    assert response.data['watchers'] == []
    assert response.data['is_watched'] == False

    response = client.post(url_watch)
    assert response.status_code == 200

    response = client.get(url_detail)
    assert response.status_code == 200
    assert response.data['watchers'] == [user.id]
    assert response.data['is_watched'] == True

    response = client.post(url_unwatch)
    assert response.status_code == 200

    response = client.get(url_detail)
    assert response.status_code == 200
    assert response.data['watchers'] == []
    assert response.data['is_watched'] == False
