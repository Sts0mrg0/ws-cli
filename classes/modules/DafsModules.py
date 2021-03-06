# -*- coding: utf-8 -*-
""" Common module class form Dafs* modules """
import time
import re
import os
from urlparse import urlparse

from classes.Registry import Registry
from classes.kernel.WSModule import WSModule
from classes.kernel.WSException import WSException
from classes.kernel.WSCounter import WSCounter
from classes.models.HostsModel import HostsModel
from classes.models.UrlsBaseModel import UrlsBaseModel
from classes.models.UrlsModel import UrlsModel
from classes.jobs.DafsJob import DafsJob
from classes.threads.DafsThread import DafsThread
from classes.threads.SDafsThread import SDafsThread

class DafsModules(WSModule):
    """ Common module class form Dafs* modules """
    logger_enable = True
    logger_name = 'dafs'
    logger_have_items = True

    def load_objects(self, queue):
        """ Method for prepare check objects, here abstract """
        pass

    def _insert_urls(self, urls):
        """ Add found urls in db """
        UrlsBase = UrlsBaseModel()
        pid = Registry().get('pData')['id']

        host_id = HostsModel().get_id_by_name(pid, self.options['host'].value)
        Urls = UrlsModel()

        added = 0
        for url in urls:
            if Urls.add(pid, host_id, url['url'], '', url['code'], url['time'], 'dafs'):
                added += 1

            paths = urlparse(url['url']).path.split("/")
            while len(paths) != 1:
                del paths[-1]
                if Urls.add(pid, host_id, "/".join(paths) + "/", '', 0, 0, 'dafs'):
                    added += 1
            UrlsBase.add_url(host_id, url['url'])

        return added

    def validate_main(self):
        """ Check users params """
        super(DafsModules, self).validate_main()

        if self.options['url'].value[0] != '/':
            raise WSException("URL must start from the root ('/') !")

    def scan_action(self):
        """ Scan action of module """
        self.enable_logger()
        self.validate_main()
        self.pre_start_inf()

        if self.options['proxies'].value:
            Registry().get('proxies').load(self.options['proxies'].value)

        if self.options['url'].value.find(self.options['msymbol'].value) == -1:
            raise WSException(
                "Symbol of object position ({0}) not found in URL ({1}) ".
                format(self.options['msymbol'].value, self.options['url'].value)
            )

        result = []

        q = DafsJob()

        loaded = self.load_objects(q)

        self.logger.log(
            "Loaded {0} words from dict ({1}-{2}).".format(loaded['all'], loaded['start'], loaded['end'])
            if (int(self.options['parts'].value) and int(self.options['part'].value)) else
            "Loaded {0} words from dict.".format(loaded['all'])
        )

        counter = WSCounter(5, 300, loaded['all'] if not loaded['end'] else loaded['end']-loaded['start'])

        w_thrds = []
        for _ in range(int(self.options['threads'].value)):
            if self.options['selenium'].value:
                worker = SDafsThread(
                    q,
                    self.options['protocol'].value,
                    self.options['host'].value,
                    self.options['url'].value,
                    self.options['method'].value.lower(),
                    self.options['msymbol'].value,
                    self.options['not-found-re'].value,
                    self.options['delay'].value,
                    self.options['ddos-detect-phrase'].value,
                    self.options['ddos-human-action'].value,
                    self.options['browser-recreate-re'].value,
                    counter,
                    result
                )
            else:
                worker = DafsThread(
                    q,
                    self.options['protocol'].value,
                    self.options['host'].value,
                    self.options['url'].value,
                    self.options['method'].value.lower(),
                    self.options['msymbol'].value,
                    self.options['not-found-re'].value,
                    self.options['not-found-codes'].value.lower(),
                    self.options['retest-codes'].value.lower(),
                    self.options['delay'].value,
                    counter,
                    result
                )
            worker.setDaemon(True)
            worker.start()
            w_thrds.append(worker)

            time.sleep(1)

        while len(w_thrds):
            if Registry().get('proxy_many_died'):
                self.logger.log("Proxy many died, stop scan")

            if Registry().get('proxy_many_died') or Registry().get('positive_limit_stop'):
                worker.done = True
                time.sleep(3)

            for worker in w_thrds:
                if worker.done:
                    del w_thrds[w_thrds.index(worker)]

                if int(time.time()) - worker.last_action > int(Registry().get('config')['main']['kill_thread_after_secs']):
                    self.logger.log("Thread killed by time")
                    del w_thrds[w_thrds.index(worker)]

            time.sleep(2)

        if Registry().get('positive_limit_stop'):
            self.logger.log("Many positive detections. Please, look items logs")
            self.logger.log("Last items:")
            for i in range(1, 5):
                print result[-i]
            exit(0)

        self.logger.log("\nInsert links in DB...")

        added = self._insert_urls(result)
        for result_row in result:
            self.logger.log("{0} {1}".format(result_row['code'], result_row['url']))
        self.logger.log("\nFound {0} URLs, inserted in database (new) - {1}.".format(len(result), added))

        self.done = True
