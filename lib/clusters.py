from typing import List, Dict, Tuple, Optional

from lib.tracking import Tracking

OUTPUT_FOLDER = "output"
CLUSTERS_FILENAME = "clusters.pickle"
CLUSTERS_FILE = OUTPUT_FOLDER + "/" + CLUSTERS_FILENAME


class Cluster:

  def __init__(self, group) -> None:
    self._initiate(set(), set(), group, 0, 0, '0', set(), set(), 0.0, [])

  def _initiate(self,
                orders,
                trackings,
                group,
                expected_cost,
                tracked_cost,
                last_ship_date='0',
                purchase_orders=set(),
                email_ids=set(),
                adjustment=0.0,
                to_email='',
                notes='',
                manual_override=False,
                non_reimbursed_trackings=set(),
                cancelled_items=[],
                last_delivery_date='') -> None:
    self.orders = orders
    self.trackings = trackings
    self.group = group
    self.expected_cost = expected_cost
    self.tracked_cost = tracked_cost
    self.last_ship_date = last_ship_date
    self.purchase_orders = purchase_orders
    self.email_ids = email_ids
    self.adjustment = adjustment
    self.to_email = to_email
    self.notes = notes
    self.manual_override = manual_override
    self.non_reimbursed_trackings = non_reimbursed_trackings
    self.cancelled_items = cancelled_items
    self.last_delivery_date = last_delivery_date

  def __setstate__(self, state) -> None:
    self._initiate(**state)

  def __str__(self) -> str:
    return "orders: %s, trackings: %s, group: %s, expected cost: %s, tracked cost: %s, last_ship_date: %s, last_delivery_date: %s, purchase_orders: %s, email_ids: %s, adjustment: %s" % (
        str(self.orders), str(self.trackings), self.group, str(self.expected_cost),
        str(self.tracked_cost), self.last_ship_date, self.last_delivery_date,
        str(self.purchase_orders), str(self.email_ids), str(self.adjustment))

  def get_header(self) -> List[str]:
    return [
        "Orders", "Trackings", "To Email", "Amount Billed", "Amount Reimbursed",
        "Non-Reimbursed Trackings", "Last Ship Date", "Last Delivery Date (Est.)", "POs", "Group",
        "Manual Cost Adjustment", "Manual Override", "Total Diff", "Notes", "Cancelled Items"
    ]

  def to_row(self) -> list:
    return [
        ", ".join(self.orders), ", ".join(self.trackings), self.to_email, self.expected_cost,
        self.tracked_cost, ", ".join(self.non_reimbursed_trackings), self.last_ship_date,
        self.last_delivery_date, "'" + ", ".join(self.purchase_orders), self.group, self.adjustment,
        self.manual_override, '=D:D - E:E - K:K', self.notes, ", ".join(self.cancelled_items)
    ]

  def merge_with(self, other) -> None:
    self.orders.update(other.orders)
    self.trackings.update(other.trackings)
    if self.group.strip() != other.group.strip():
      self.group += f", {other.group.strip()}"
    self.expected_cost += other.expected_cost
    self.tracked_cost += other.tracked_cost
    self.last_ship_date = max(self.last_ship_date, other.last_ship_date)
    self.last_delivery_date = max(self.last_delivery_date, other.last_delivery_date)
    self.purchase_orders.update(other.purchase_orders)
    self.email_ids.update(other.email_ids)
    self.adjustment += other.adjustment
    if self.notes and other.notes:
      self.notes += ", " + other.notes
    elif other.notes:
      self.notes = other.notes
    # Always clear manual overriding status on a cluster merge.
    if (self.manual_override or other.manual_override):
      print(f"Newly merged cluster {self.orders} manual override unset.")
      self.manual_override = False
    self.non_reimbursed_trackings.update(other.non_reimbursed_trackings)
    self.cancelled_items.extend(other.cancelled_items)


def find_cluster(order_to_cluster: Dict[str, Cluster], tracking: Tracking) -> Optional[Cluster]:
  for order in tracking.order_ids:
    if order in order_to_cluster:
      return order_to_cluster[order]
  return None


def update_clusters(all_clusters: List[Cluster], trackings: List[Tracking]) -> None:
  order_to_cluster = {}
  for tracking in trackings:
    cluster = find_cluster(order_to_cluster, tracking)
    if cluster is None:
      cluster = Cluster(tracking.group)
      all_clusters.append(cluster)

    # map order -> cluster for quick combine-by-order operations
    for order in tracking.order_ids:
      order_to_cluster[order] = cluster

    # If we are adding a new tracking or order ID, unset the manual override
    # status of the cluster.
    override_overridden = False
    if (len(set(tracking.order_ids).difference(set(cluster.orders))) > 0 or
        tracking.tracking_number not in cluster.trackings):
      if cluster.manual_override:
        override_overridden = True
      cluster.manual_override = False
    cluster.orders.update(tracking.order_ids)
    cluster.trackings.add(tracking.tracking_number)
    cluster.last_ship_date = max(cluster.last_ship_date, str(tracking.ship_date))
    cluster.last_delivery_date = max(cluster.last_delivery_date, str(tracking.delivery_date))
    cluster.to_email = tracking.to_email
    if override_overridden:
      print(f"Cluster {cluster.orders} manual override unset because of newly "
            "added trackings or orders.")


def merge_orders(clusters) -> list:
  """ Merges together orders that share a common purchase order or email ID. """
  print("Merging clusters by PO or email ID")
  while True:
    prev_length = len(clusters)
    clusters = run_merge_iteration(clusters)
    if len(clusters) == prev_length:
      break
  return clusters


def fill_email_po_group_maps(cluster: Cluster, email_to_cluster: Dict[str, Cluster],
                             po_group_to_cluster: Dict[Tuple[str, str], Cluster]) -> None:
  for po in cluster.purchase_orders:
    po_group_to_cluster[(po, cluster.group)] = cluster
  for email in cluster.email_ids:
    email_to_cluster[email] = cluster


def run_merge_iteration(clusters: List[Cluster]) -> list:
  result = []
  email_to_cluster: Dict[str, Cluster] = {}
  po_group_to_cluster: Dict[Tuple[str, str], Cluster] = {}
  for cluster in clusters:
    to_merge = find_by_shared_attr(cluster, email_to_cluster, po_group_to_cluster)
    if to_merge:
      to_merge.merge_with(cluster)
      fill_email_po_group_maps(to_merge, email_to_cluster, po_group_to_cluster)
    else:
      result.append(cluster)
      fill_email_po_group_maps(cluster, email_to_cluster, po_group_to_cluster)
  return result


def find_by_shared_attr(cluster: Cluster, email_to_cluster: Dict[str, Cluster],
                        po_group_to_cluster: Dict[Tuple[str, str], Cluster]) -> Optional[Cluster]:
  for po in cluster.purchase_orders:
    if (po, cluster.group) in po_group_to_cluster:
      return po_group_to_cluster[(po, cluster.group)]
  for email in cluster.email_ids:
    if email in email_to_cluster:
      return email_to_cluster[email]
  return None


def from_row(header, row) -> Cluster:
  if 'Orders' in header:
    orders = set([o.strip() for o in str(row[header.index('Orders')]).split(',')])
  else:
    orders = set()

  if 'Trackings' in header:
    trackings = set([t.strip() for t in str(row[header.index('Trackings')]).split(',')])
  else:
    trackings = set()

  expected_cost_str = row[header.index('Amount Billed')] if 'Amount Billed' in header else ''
  expected_cost = float(expected_cost_str) if expected_cost_str else 0.0
  tracked_cost_str = row[header.index("Amount Reimbursed")] if "Amount Reimbursed" in header else ''
  tracked_cost = float(tracked_cost_str) if tracked_cost_str else 0.0
  non_reimbursed_str = str(
      row[header.index("Non-Reimbursed Trackings")]) if "Non-Reimbursed Trackings" in header else ""
  non_reimbursed_trackings = set([t.strip() for t in non_reimbursed_str.split(',')
                                 ]) if non_reimbursed_str else set()
  last_ship_date = row[header.index('Last Ship Date')] if 'Last Ship Date' in header else '0'
  last_delivery_date = row[header.index(
      'Last Delivery Date (Est.)')] if 'Last Delivery Date (Est.)' in header else ''
  pos_string = str(row[header.index('POs')]) if 'POs' in header else ''
  pos = set([s.strip() for s in pos_string.split(',')]) if pos_string else set()
  email_ids = set()  # Set this if we want email IDs in the Sheet
  group = row[header.index('Group')] if 'Group' in header else ''
  adj_string = row[header.index(
      "Manual Cost Adjustment")] if "Manual Cost Adjustment" in header else ''
  adjustment = float(adj_string) if adj_string else 0.0
  manual_override = row[header.index('Manual Override')] if 'Manual Override' in header else False
  to_email = row[header.index('To Email')] if 'To Email' in header else ''
  notes = str(row[header.index('Notes')]) if 'Notes' in header else ''
  cancelled_items_str = str(
      row[header.index("Cancelled Items")]) if "Cancelled Items" in header else ""
  cancelled_items = [i.strip() for i in cancelled_items_str.split(',')
                    ] if cancelled_items_str else []
  cluster = Cluster(group)
  cluster._initiate(orders, trackings, group, expected_cost, tracked_cost, last_ship_date, pos,
                    email_ids, adjustment, to_email, notes, manual_override,
                    non_reimbursed_trackings, cancelled_items, last_delivery_date)
  return cluster
