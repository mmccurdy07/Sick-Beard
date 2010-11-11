# Author: Nic Wolfe <nic@wolfeden.ca>
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of Sick Beard.
#
# Sick Beard is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Sick Beard is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Sick Beard.  If not, see <http://www.gnu.org/licenses/>.



import urllib
import datetime
import re

import xml.etree.cElementTree as etree

import sickbeard
import generic

from sickbeard import classes, sceneHelpers

from sickbeard import exceptions
from sickbeard.common import *
from sickbeard import logger
from sickbeard import tvcache

from lib.tvnamer.utils import FileParser
from lib.tvnamer import tvnamer_exceptions

class NewznabProvider(generic.NZBProvider):

	def __init__(self, name, url, key=''):

		generic.NZBProvider.__init__(self, name)

		self.cache = NewznabCache(self)

		self.url = url
		self.key = key

		self.enabled = True
		self.supportsBacklog = True

		self.default = False

	def configStr(self):
		return self.name + '|' + self.url + '|' + self.key + '|' + str(int(self.enabled))

	def imageName(self):
		return 'newznab.gif'

	def isEnabled(self):
		return self.enabled

	def findEpisode (self, episode, manualSearch=False):

		nzbResults = generic.NZBProvider.findEpisode(self, episode, manualSearch)

		# if we got some results then use them no matter what.
		# OR
		# return anyway unless we're doing a backlog/missing or manual search
		if nzbResults or not manualSearch:
			return nzbResults

		itemList = []
		results = []

		itemList += self._doSearch(episode.show, episode.season, episode.episode)

		for item in itemList:

			title = item.findtext('title')
			url = item.findtext('link')

			quality = self.getQuality(item)

			if not episode.show.wantEpisode(episode.season, episode.episode, quality, manualSearch):
				logger.log(u"Ignoring result "+title+" because we don't want an episode that is "+Quality.qualityStrings[quality], logger.DEBUG)
				continue

			logger.log(u"Found result " + title + " at " + url, logger.DEBUG)

			result = self.getResult([episode])
			result.url = url
			result.name = title
			result.quality = quality

			results.append(result)

		return results


	def _get_season_search_strings(self, show, season=None, episode=None):

		params = {}

		if not show:
			return params
		
		# search directly by tvrage id
		params['rid'] = show.tvrid

		if season != None:
			# air-by-date means &season=2010&q=2010.03, no other way to do it atm
			if show.is_air_by_date:
				params['season'] = season.split('-')[0]
				params['q'] = season.replace('-', '.')
			else:
				params['season'] = season

			if episode:
				params['ep'] = episode
		
		logger.log("using "+str(params))

		return [params]

	def _doGeneralSearch(self, search_string):
		return self._doSearch({'q': search_string})

	#def _doSearch(self, show, season=None, episode=None, search=None):
	def _doSearch(self, search_params):

		params = {"t": "tvsearch",
				  "maxage": sickbeard.USENET_RETENTION,
				  "limit": 100,
				  "cat": '5030,5040'}

		logger.log("params: "+str(params)+" search_params: "+str(search_params))

		if search_params:
			params.update(search_params)

		if self.key:
			params['apikey'] = self.key

		searchURL = self.url + 'api?' + urllib.urlencode(params)

		logger.log(u"Search url: " + searchURL, logger.DEBUG)

		data = self.getURL(searchURL)

		if data == None:
			return []

		try:
			responseSoup = etree.ElementTree(etree.XML(data))
			items = responseSoup.getiterator('item')
		except Exception, e:
			logger.log(u"Error trying to load "+self.name+" RSS feed: "+str(e).decode('utf-8'), logger.ERROR)
			logger.log(u"RSS data: "+data, logger.DEBUG)
			return []

		if responseSoup.getroot().tag == 'error':
			code = responseSoup.getroot().get('code')
			if code == '100':
				raise exceptions.AuthException("Your API key for "+self.name+" is incorrect, check your config.")
			elif code == '101':
				raise exceptions.AuthException("Your account on "+self.name+" has been suspended, contact the administrator.")
			elif code == '102':
				raise exceptions.AuthException("Your account isn't allowed to use the API on "+self.name+", contact the administrator")
			else:
				logger.log(u"Unknown error given from "+self.name+": "+responseSoup.getroot().get('description'), logger.ERROR)
				return []

		if responseSoup.getroot().tag != 'rss':
			logger.log(u"Resulting XML from "+self.name+" isn't RSS, not parsing it", logger.ERROR)
			return []

		results = []

		for curItem in items:
			title = curItem.findtext('title')
			url = curItem.findtext('link')

			if not title or not url:
				logger.log(u"The XML returned from the "+self.name+" RSS feed is incomplete, this result is unusable: "+data, logger.ERROR)
				continue

			url = url.replace('&amp;','&')

			results.append(curItem)

		return results

	def findPropers(self, date=None):

		return []

		results = []

		for curResult in self._doGeneralSearch("proper repack"):

			match = re.search('(\w{3}, \d{1,2} \w{3} \d{4} \d\d:\d\d:\d\d) [\+\-]\d{4}', curResult.findtext('pubDate'))
			if not match:
				continue

			resultDate = datetime.datetime.strptime(match.group(1), "%a, %d %b %Y %H:%M:%S")

			if date == None or resultDate > date:
				results.append(classes.Proper(curResult.findtext('title'), curResult.findtext('link'), resultDate))

		return results

class NewznabCache(tvcache.TVCache):

	def __init__(self, provider):

		tvcache.TVCache.__init__(self, provider)

		# only poll newznab providers every 15 minutes max
		self.minTime = 15

	def _getRSSData(self):

		params = {"t": "tvsearch",
				  "age": sickbeard.USENET_RETENTION,
				  "cat": '5040,5030'}

		if self.provider.key:
			params['apikey'] = self.provider.key

		url = self.provider.url + 'api?' + urllib.urlencode(params)

		logger.log(self.provider.name + " cache update URL: "+ url, logger.DEBUG)

		data = self.provider.getURL(url)

		return data

	def _checkAuth(self, data):

		try:
			responseSoup = etree.ElementTree(etree.XML(data))
		except Exception, e:
			return True

		if responseSoup.getroot().tag == 'error':
			code = responseSoup.getroot().get('code')
			if code == '100':
				raise exceptions.AuthException("Your API key for "+self.provider.name+" is incorrect, check your config.")
			elif code == '101':
				raise exceptions.AuthException("Your account on "+self.provider.name+" has been suspended, contact the administrator.")
			elif code == '102':
				raise exceptions.AuthException("Your account isn't allowed to use the API on "+self.provider.name+", contact the administrator")
			else:
				logger.log(u"Unknown error given from "+self.provider.name+": "+responseSoup.getroot().get('description'), logger.ERROR)
				return False

		return True
