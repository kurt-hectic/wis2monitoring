import os
import json
import logging
import jq

from baseprocessor import BaseProcessor

from jsonschema import Draft202012Validator
from prometheus_client import  Counter


log_level = os.getenv("LOG_LEVEL", "INFO")
level = logging.getLevelName(log_level)


logging.basicConfig(format='%(asctime)s %(levelname)s:%(message)s',level=level, 
    handlers=[  logging.StreamHandler()] )



jq_canonical_links = jq.compile('.links[] | select(.rel=="canonical").href')

class DepuplicationProcessor(BaseProcessor):

    draft_202012_validator = None

    NR_INVALID_MESSAGES = Counter('invalid_messages_total', 'Number of messages with invalid notification schema')
    NR_DUPLICATES = Counter('duplicate_messages_total', 'Number of duplicate messages')



    def __init__(self):
        BaseProcessor.__init__(self,group_id="my-consumer-deduplication-1")

        schema = json.loads(open("wis2-notification-message-bundled.json").read())
        Draft202012Validator.check_schema(schema)
        self.draft_202012_validator = Draft202012Validator(schema)
        


    def __process_messages__(self,notifications):
        error_messages = []
        
        initial_length = len(notifications)
        logging.debug(f"{initial_length} new messages")

        # only accept valid notificatons 
        notifications = [n for n in notifications if self.draft_202012_validator.is_valid(n)]
        nr_non_valid = initial_length - len(notifications)
        if nr_non_valid>0:
            logging.warning("filtered out %s non-valid records inside one batch ", nr_non_valid )
            self.NR_INVALID_MESSAGES.inc(nr_non_valid)
            # add non-valid messages to error list
            for n in [n for n in notifications if not self.draft_202012_validator.is_valid(n)]:
                error_messages.append({"reason" : "non valid" , "data" : n })

        # filter out possible duplicates inside the batch
        data_ids_links = {}
        notifications_new = []
        for n in notifications:
            if n["properties"]["data_id"] not in data_ids_links:
                data_ids_links[n["properties"]["data_id"]] = []
                notifications_new.append(n)
            data_ids_links[n["properties"]["data_id"]].append( jq_canonical_links.input(n).all() ) 

        notifications = []
        for n in notifications_new:
            n["_meta"]["cache_links"] = list(set([url for lou in data_ids_links[n["properties"]["data_id"]] for url in lou ])) #flatten list of list of links and only use unique links
            notifications.append(n)

        nr_duplicate_in_batch = (initial_length+nr_non_valid)-len(notifications)
        if nr_duplicate_in_batch>0:
            self.NR_DUPLICATES.inc(nr_duplicate_in_batch)
            logging.debug("filtered out %s duplicate records inside one batch ", nr_duplicate_in_batch )


        keys = [n["properties"]["data_id"] for n in notifications]

        return notifications,keys,error_messages


if __name__ == "__main__":
   
    logging.info("starting deduplication processor")
    processor = DepuplicationProcessor()
    processor.start_consuming()