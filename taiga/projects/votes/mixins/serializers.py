# Copyright (C) 2015 Andrey Antukh <niwi@niwi.be>
# Copyright (C) 2015 Jesús Espino <jespinog@gmail.com>
# Copyright (C) 2015 David Barragán <bameda@dbarragan.com>
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

from taiga.base.api import serializers


class BaseVotedResourceSerializer(serializers.ModelSerializer):
    def get_votes_counter(self, obj):
        # The "votes_count" attribute is attached in the get_queryset of the viewset.
        return getattr(obj, "votes_count", 0) or 0

    def get_is_voted(self, obj):
        # The "is_voted" attribute is attached in the get_queryset of the viewset.
        return getattr(obj, "is_voted", False) or False


class LikedResourceSerializerMixin(BaseVotedResourceSerializer):
    likes = serializers.SerializerMethodField("get_votes_counter")
    is_liked = serializers.SerializerMethodField("get_is_voted")


class VotedResourceSerializerMixin(BaseVotedResourceSerializer):
    votes = serializers.SerializerMethodField("get_votes_counter")
    is_voted = serializers.SerializerMethodField("get_is_voted")
