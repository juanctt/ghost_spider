# -*- coding: utf-8 -*-

from scrapy.spider import Spider
from scrapy.selector import Selector
from scrapy.http import Request
from ghost_spider.items import GhostSpiderItem
from ghost_spider import helper
import logging
from scrapy import log as scrapyLog
from ghost_spider.elastic import LocationHs


class TarantulaSpider(Spider):
  name = "tarantula"
  allowed_domains = ["localhost"]
  # target_base_url = "file://localhost/Users/jctt/Developer/crawler/ghost_spider/samples"
  # start_urls = [
  #     "file://localhost/Users/jctt/Developer/crawler/ghost_spider/samples/target_list_of_places.html"
  # ]
  #allowed_domains = ["localhost", "tripadvisor.com", "tripadvisor.jp", "tripadvisor.es", "tripadvisor.fr", "daodao.com"]
  target_base_url = "http://www.tripadvisor.com"
  start_urls = [
      "http://localhost/AllLocations-g1-c1-Hotels-World.html"
  ]
  log = None
  total_count = 0L

  def __init__(self, name=None, **kwargs):
    from ghost_spider.settings import LOG_OUTPUT_FILE
    self.log = logging.getLogger(self.name)
    ch = logging.FileHandler(LOG_OUTPUT_FILE)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    ch.setLevel(logging.ERROR)
    ch.setFormatter(formatter)
    self.log.addHandler(ch)
    self.total_count = 0L
    super(TarantulaSpider, self).__init__(self.name, **kwargs)

  def parse(self, response):
    count = 0
    download_list = None
    current_level = long(response.meta.get('area_level') or 1)
    sel = Selector(response)
    links = sel.xpath(helper.SEL_LIST_PLACES).extract()

    # Get the list of countries that needs to be scrapped
    if current_level == 1:
      download_list = sel.xpath(helper.SEL_ALLOW_PLACES).extract()
      if not download_list or not len(download_list):
        return None
      download_list = download_list[0].split(u',')
    if links:
      for link in links:
        count += 1
        area_name = helper.place_sel_name.findall(link)[0]
        # skip country if is not in the list
        if current_level == 1 and area_name.lower() not in download_list:
          continue
        print area_name
        area_link = self.target_base_url + helper.place_sel_link.findall(link)[0]
        request = Request(area_link, callback=self.parse, errback=self.parse_err)
        request.meta['area_name'] = area_name
        # Go to the next level
        request.meta['area_level'] = current_level + 1
        yield request
    else:
      # possible last level
      links = sel.xpath(helper.SEL_LIST_PLACES_LAST).extract()
      if links:
        if not response.meta.get('is_more'):
          # load additional list of places
          links_more = sel.xpath(helper.SEL_LIST_MORE).extract()
          for l in links_more:
            count += 1
            area_name = "More Links"
            area_link = self.target_base_url + helper.place_sel_link.findall(l)[0]
            request = Request(area_link, callback=self.parse, errback=self.parse_err)
            request.meta['area_name'] = area_name
            request.meta['is_more'] = True
            request.meta['area_level'] = current_level
            scrapyLog.msg('Loading more pages, %s' % area_link, level=scrapyLog.INFO)
            yield request
        for link in links:
          area_name = helper.place_sel_name_last.findall(link)[0]
          area_link = self.target_base_url + helper.place_sel_link_last.findall(link)[0]
          # don't scrap the page if it was crawled
          if LocationHs.check_by_url(area_link):
            scrapyLog.msg(u'ignored %s' % area_link, level=scrapyLog.INFO)
            continue
          request = Request(area_link, callback=self.parse_place, errback=self.parse_err)
          request.meta['area_name'] = area_name
          request.meta['area_level'] = current_level + 1
          yield request
          count += 1
        self.total_count += count
        print u'found = %s' % self.total_count
    if response.meta.get('area_name'):
      message = u'%s> %s found(%s) | total(%s)' % ('-----' * current_level, response.meta['area_name'], count, self.total_count)
      print message
      scrapyLog.msg(message, level=scrapyLog.INFO)

  def parse_err(self, failure):
    # save in the log the pages that couldn't be scrapped
    self.log.error(u'%s -- %s' % (failure.getErrorMessage(), failure.getBriefTraceback()))
    
  def parse_place(self, response):
    if response.meta.get('area_name') and self.log:
      scrapyLog.msg(u'%s> %s' % ("-----" * response.meta.get('area_level') or 1, response.meta['area_name']), level=scrapyLog.INFO)
    sel = Selector(response)
    item = GhostSpiderItem()
    item['page_url'] = response.url
    item['page_breadcrumbs'] = sel.xpath(helper.SEL_BREADCRUMBS).extract()
    item['name'] = sel.xpath(helper.SEL_HOTEL_NAME).extract()
    item['phone'] = sel.xpath(helper.SEL_PHONE_NUMBER).extract()
    item['address_area_name'] = sel.xpath(helper.SEL_AREA_NAME).extract()
    item['address_street'] = sel.xpath(helper.SEL_AREA_STREET).extract()
    item['address_locality'] = sel.xpath(helper.SEL_AREA_LOCALITY).extract()
    item['address_region'] = sel.xpath(helper.SEL_AREA_REGION).extract()
    item['address_zip'] = sel.xpath(helper.SEL_AREA_ZIP).extract()
    item['amenity'] = sel.xpath(helper.SEL_AMENITIES).extract()
    item['rating'] = sel.xpath(helper.SEL_RATING).re(r'(.*)\s*of 5')
    item['popularity'] = sel.xpath(helper.SEL_PERCENT).re(r'(.*)\s*%')
    item['page_body'] = helper.get_body(sel)
    links = {
      'ja': sel.xpath(helper.SEL_JAPANESE_PAGE).extract(),
    }
    if self.need_french_page(item['page_breadcrumbs']):
      links['fr'] = sel.xpath(helper.SEL_FRENCH_PAGE).extract()
    elif self.need_spanish_page(item['page_breadcrumbs']):
      links['es'] = sel.xpath(helper.SEL_SPANISH_PAGE).extract()

    for name, link in links.iteritems():
      if not link:
        self.log.error("couldn't index this page | %s" % response.url)
        return None
      links[name] = link[0]
    request = Request(links['ja'], callback=self.parse_local_page)
    request.meta['remain'] = ['ja']
    request.meta['links'] = links
    request.meta['item'] = item
    return request

  def parse_local_page(self, response):
    current = response.meta['remain'][0]
    remain = response.meta['remain'][1:]
    sel = Selector(response)
    item = response.meta['item']
    item['name_%s' % current] = sel.xpath(helper.SEL_HOTEL_NAME).extract()
    item['address_area_name_%s' % current] = sel.xpath(helper.SEL_AREA_NAME).extract()
    item['address_street_%s' % current] = sel.xpath(helper.SEL_AREA_STREET).extract()
    item['address_locality_%s' % current] = sel.xpath(helper.SEL_AREA_LOCALITY).extract()
    item['address_region_%s' % current] = sel.xpath(helper.SEL_AREA_REGION).extract()
    item['address_zip_%s' % current] = sel.xpath(helper.SEL_AREA_ZIP).extract()
    item['amenity_%s' % current] = sel.xpath(helper.SEL_AMENITIES).extract()
    item['page_body_%s' % current] = helper.get_body(sel)
    if remain and len(remain) > 0:
      from ghost_spider.settings import REQUEST_HEADERS
      next_lang = remain[0]
      request = Request(response.meta['links'][next_lang], headers=REQUEST_HEADERS[next_lang], callback=self.parse_local_page, errback=self.parse_err)
      request.meta['remain'] = remain
      request.meta['links'] = response.meta['links']
      request.meta['item'] = item
      return request
    return item

  def need_french_page(breadcrumbs):
    return u'France' in breadcrumbs

  def need_spanish_page(breadcrumbs):
    return u'Spain' in breadcrumbs
