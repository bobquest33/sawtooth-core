# Copyright 2016 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------------

import queue
from threading import Condition

from sawtooth_validator.scheduler.base import BatchStatus
from sawtooth_validator.scheduler.base import TxnInformation
from sawtooth_validator.scheduler.base import Scheduler
from sawtooth_validator.scheduler.base import SchedulerIterator


class SerialScheduler(Scheduler):
    """Serial scheduler which returns transactions in the natural order.

    This scheduler will scheduler one transaction at a time (only one may be
    unapplied), in the exact order provided as batches were added to the
    scheduler.

    This scheduler is intended to be used for comparison to more complex
    schedulers - for tests related to performance, correctness, etc.
    """
    def __init__(self):
        self._txn_queue = queue.Queue()
        self._scheduled_transactions = []
        self._batch_statuses = {}
        self._txn_to_batch = {}
        self._in_progress_transaction = None
        self._final = False
        self._condition = Condition()

    def __iter__(self):
        return SchedulerIterator(self, self._condition)

    def set_status(self, txn_signature, status, state_hash=None):
        with self._condition:
            if txn_signature not in self._txn_to_batch:
                raise ValueError("transaction not in any batches: {}".format(
                    txn_signature))
            batch_signature = self._txn_to_batch[txn_signature]
            batch_status = BatchStatus(status, state_hash)
            self._batch_statuses[batch_signature] = batch_status

    def add_batch(self, batch, state_hash=None):
        with self._condition:
            batch_signature = batch.signature
            batch_length = len(batch.transactions)
            for idx, txn in enumerate(batch.transactions):
                self._txn_to_batch[txn.signature] = batch_signature
                if idx == batch_length - 1:
                    txn_info = TxnInformation(txn, True, True)
                else:
                    txn_info = TxnInformation(txn, True, False)
                self._txn_queue.put(txn_info)
            self._condition.notify_all()

    def batch_status(self, batch_signature):
        with self._condition:
            return self._batch_statuses.get(batch_signature)

    def count(self):
        with self._condition:
            return len(self._scheduled_transactions)

    def get_transaction(self, index):
        with self._condition:
            return self._scheduled_transactions[index]

    def next_transaction(self):
        with self._condition:
            if self._in_progress_transaction is not None:
                return None
            try:
                txn_info = self._txn_queue.get(block=False)
            except queue.Empty:
                return None

            self._in_progress_transaction = txn_info.txn.signature
            self._scheduled_transactions.append(txn_info)
            return txn_info

    def mark_as_applied(self, transaction_signature):
        if (self._in_progress_transaction is None or
                self._in_progress_transaction != transaction_signature):
            raise ValueError("transaction not in progress: {}",
                             transaction_signature)
        self._in_progress_transaction = None

    def finalize(self):
        with self._condition:
            self._final = True
            self._condition.notify_all()

    def complete(self):
        with self._condition:
            if not self._final:
                return False
            if self._txn_queue.empty():
                return True
            return False
