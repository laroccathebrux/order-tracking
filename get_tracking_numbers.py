import clusters
import sys
import traceback
import yaml
from amazon_tracking_retriever import AmazonTrackingRetriever
from bestbuy_tracking_retriever import BestBuyTrackingRetriever
from driver_creator import DriverCreator
from email_sender import EmailSender
from expected_costs import ExpectedCosts
from group_site_manager import GroupSiteManager
from sheets_uploader import SheetsUploader
from tracking_output import TrackingOutput

CONFIG_FILE = "config.yml"


def send_error_email(email_sender, subject):
  type, value, trace = sys.exc_info()
  formatted_trace = traceback.format_tb(trace)
  lines = [str(type), str(value)] + formatted_trace
  email_sender.send_email_content(subject, "\n".join(lines))


def fill_expected_costs(all_clusters, config):
  expected_costs = ExpectedCosts(config)
  for cluster in all_clusters:
    total_expected_cost = sum([
        expected_costs.get_expected_cost(order_id)
        for order_id in cluster.orders
    ])
    cluster.expected_cost = total_expected_cost


if __name__ == "__main__":
  driver_creator = DriverCreator(sys.argv)

  with open(CONFIG_FILE, 'r') as config_file_stream:
    config = yaml.safe_load(config_file_stream)
  email_config = config['email']
  email_sender = EmailSender(email_config)

  print("Retrieving Amazon tracking numbers from email...")
  amazon_tracking_retriever = AmazonTrackingRetriever(config, driver_creator)
  try:
    groups_dict = amazon_tracking_retriever.get_trackings()
  except:
    send_error_email(email_sender, "Error retrieving Amazon emails")
    raise

  if amazon_tracking_retriever.failed_email_ids:
    print(
        "Found %d Amazon emails without buying group labels and marked them as unread. Continuing..."
        % len(amazon_tracking_retriever.failed_email_ids))

  print("Retrieving Best Buy tracking numbers from email...")
  bestbuy_tracking_retriever = BestBuyTrackingRetriever(config, driver_creator)
  try:
    bb_groups_dict = bestbuy_tracking_retriever.get_trackings()
    for group, trackings in bb_groups_dict.items():
      if group in groups_dict:
        groups_dict[group].extend(trackings)
      else:
        groups_dict[group] = trackings
  except:
    send_error_email(email_sender, "Error retrieving BB emails")
    raise

  if bestbuy_tracking_retriever.failed_email_ids:
    print(
        "Found %d BB emails without buying group labels and marked them as unread. Continuing..."
        % len(bestbuy_tracking_retriever.failed_email_ids))

  try:
    total_trackings = sum(
        [len(trackings) for trackings in groups_dict.values()])
    print("Found %d total tracking numbers" % total_trackings)

    # We only need to process and upload new tracking numbers if there are any;
    # otherwise skip straight to processing existing locally stored data.
    if total_trackings > 0:
      email_sender.send_email(groups_dict)

      print("Uploading tracking numbers...")
      group_site_manager = GroupSiteManager(config, driver_creator)
      try:
        group_site_manager.upload(groups_dict)
      except:
        send_error_email(email_sender, "Error uploading tracking numbers")
        raise

      print("Adding results to Google Sheets")
      sheets_uploader = SheetsUploader(config)
      try:
        sheets_uploader.upload(groups_dict)
      except:
        send_error_email(email_sender, "Error uploading to Google Sheets")
        raise

    print("Writing results to file")
    tracking_output = TrackingOutput()
    try:
      tracking_output.save_trackings(groups_dict)
    except:
      send_error_email(email_sender, "Error writing output file")
      raise

    print("Getting all tracking objects")
    try:
      trackings_dict = tracking_output.get_existing_trackings()
    except:
      send_error_email(email_sender,
                       "Error retrieving tracking objects from file")
      raise

    print("Converting to Cluster objects")
    try:
      all_clusters = clusters.get_existing_clusters()
      clusters.update_clusters(all_clusters, trackings_dict)
    except:
      send_error_email(email_sender, "Error converting to Cluster objects")
      raise

    print("Filling out expected costs and writing result to disk")
    try:
      fill_expected_costs(all_clusters, config)
      clusters.write_clusters(all_clusters)
    except:
      send_error_email(email_sender,
                       "Error filling expected costs + writing to disk")
      raise

    print("Done")
  except:
    print(
        "Exception thrown after looking at the emails. Marking all relevant emails as unread to reset."
    )
    amazon_tracking_retriever.back_out_of_all()
    print("Marked all as unread")
    raise
