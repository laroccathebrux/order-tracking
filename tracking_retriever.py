import re
import collections
import imaplib
import urllib3
import time

class Tracking:

    def __init__(self, tracking_number, group, order_number):
        self.tracking_number = tracking_number
        self.group = group
        self.order_number = order_number

    def __str__(self):
        return "number: %s, group: %s, order: %s" % (self.tracking_number, self.group, self.order_number)

class TrackingRetriever:

    first_regex = r'.*<a href="(http[^"]*ship-track[^"]*)"'
    second_regex = r'.*<a hr[^"]*=[^"]*"(http[^"]*progress-tracker[^"]*)"'

    order_from_url_regex = r'.*orderId%3D([0-9\-]+)'

    def __init__(self, config, driver_creator):
        self.config = config
        self.email_config = config['email']
        self.driver_creator = driver_creator

    def get_trackings(self):
        groups_dict = collections.defaultdict(list)
        email_ids = self.get_email_ids()
        trackings = [self.get_tracking(email_id) for email_id in email_ids]

        for tracking in trackings:
            groups_dict[tracking.group].append(tracking)
        return groups_dict

    def get_buying_group(self, raw_email):
        raw_email = raw_email.upper()
        for group in self.config['groups'].keys():
            group_keys = self.config['groups'][group]['keys']
            for group_key in group_keys:
                if group_key.upper() in raw_email:
                    return group
        print(raw_email)
        raise Exception("Unknown buying group")

    def get_url_from_email(self, raw_email):
        matches = re.match(self.first_regex, str(raw_email))
        if not matches:
            matches = re.match(self.second_regex, str(raw_email))
        return matches.group(1)

    def get_order_id_from_url(self, url):
        match = re.match(self.order_from_url_regex, url)
        return match.group(1)

    def get_tracking(self, email_id):
        mail = self.get_amazon_folder()

        result, data = mail.fetch(bytes(email_id, 'utf-8'), "(RFC822)")
        raw_email = str(data[0][1]).replace("=3D", "=").replace('=\\r\\n', '')
        url = self.get_url_from_email(raw_email)
        tracking_number = self.get_tracking_info(url)
        group = self.get_buying_group(raw_email)
        order_id = self.get_order_id_from_url(url)
        return Tracking(tracking_number, group, order_id)

    def get_tracking_info(self, amazon_url):
        driver = self.load_url(amazon_url)
        try:
            element = driver.find_element_by_xpath("//*[contains(text(), 'Tracking ID')]")
            regex = r'Tracking ID: ([A-Z0-9]+)'
            match = re.match(regex, element.text)
            tracking_number = match.group(1)
            return tracking_number
        finally:
            driver.close()

    def load_url(self, url):
        driver = self.driver_creator.new()
        driver.get(url)
        time.sleep(3) # wait for page load because the timeouts can be buggy
        return driver

    def get_amazon_folder(self,):
        mail = imaplib.IMAP4_SSL(self.email_config['imapUrl'])
        mail.login(self.email_config['username'], self.email_config['password'])
        mail.select(self.email_config['amazonFolderName'])
        return mail

    def get_email_ids(self):
        mail = self.get_amazon_folder()
        status, response = mail.search(None, '(UNSEEN)', '(SUBJECT "shipped")')
        email_ids = response[0].decode('utf-8')

        return email_ids.split()
