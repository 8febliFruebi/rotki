from abc import ABCMeta
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Optional, cast

from rotkehlchen.accounting.mixins.event import AccountingEventMixin, AccountingEventType
from rotkehlchen.accounting.structures.types import (
    ActionType,
    HistoryEventSubType,
    HistoryEventType,
)
from rotkehlchen.errors.serialization import DeserializationError
from rotkehlchen.serialization.deserialize import deserialize_evm_address, deserialize_fval
from rotkehlchen.types import ChecksumEvmAddress, Location, TimestampMS

from .balance import Balance

if TYPE_CHECKING:
    from rotkehlchen.accounting.pot import AccountingPot

from rotkehlchen.constants.assets import A_ETH

from .base import HISTORY_EVENT_DB_TUPLE_WRITE, HistoryBaseEntry, HistoryBaseEntryType

ETH_STAKING_EVENT_DB_TUPLE_READ = tuple[
    int,            # identifier
    int,            # timestamp
    Optional[str],  # location label
    str,            # amount
    str,            # usd value
    str,            # event_subtype
    int,            # validator_index
    int,            # is_exit_or_blocknumber
]


class EthStakingEvent(HistoryBaseEntry, metaclass=ABCMeta):
    """An ETH staking related event. Block production/withdrawal"""

    def __init__(
            self,
            event_identifier: str,
            sequence_index: int,
            event_type: HistoryEventType,
            event_subtype: HistoryEventSubType,
            validator_index: int,
            timestamp: TimestampMS,
            balance: Balance,
            location_label: ChecksumEvmAddress,
            is_exit_or_blocknumber: int,
            notes: str,
            identifier: Optional[int] = None,
    ) -> None:
        self.validator_index = validator_index
        self.is_exit_or_blocknumber = is_exit_or_blocknumber
        super().__init__(
            event_identifier=event_identifier,
            sequence_index=sequence_index,
            timestamp=timestamp,
            location=Location.ETHEREUM,
            event_type=event_type,
            event_subtype=event_subtype,
            asset=A_ETH,
            balance=balance,
            location_label=location_label,
            notes=notes,
        )

    def __eq__(self, other: Any) -> bool:
        return (
            HistoryBaseEntry.__eq__(self, other) is True and
            self.validator_index == other.validator_index and
            self.is_exit_or_blocknumber == other.is_exit_or_blocknumber
        )


class EthWithdrawalEvent(EthStakingEvent):
    """An ETH Withdrawal event"""

    def __init__(
            self,
            validator_index: int,
            timestamp: TimestampMS,
            balance: Balance,
            withdrawal_address: ChecksumEvmAddress,
            is_exit: bool,
            identifier: Optional[int] = None,
    ) -> None:
        super().__init__(
            event_identifier=f'eth2_withdrawal_{validator_index}_{timestamp}',
            sequence_index=0,
            timestamp=timestamp,
            event_type=HistoryEventType.STAKING,
            event_subtype=HistoryEventSubType.REMOVE_ASSET,
            validator_index=validator_index,
            balance=balance,
            location_label=withdrawal_address,
            is_exit_or_blocknumber=is_exit,
            notes=f'Withdrew {balance.amount} ETH from validator {validator_index}',
        )

    def __repr__(self) -> str:
        return f'EthWithdrawalEvent({self.validator_index=}, {self.timestamp=}, is_exit={self.is_exit_or_blocknumber})'  # noqa: E501

    def serialize_for_db(self) -> tuple[HISTORY_EVENT_DB_TUPLE_WRITE, tuple[int, int]]:
        base_tuple = self._serialize_base_tuple_for_db(HistoryBaseEntryType.ETH_WITHDRAWAL_EVENT)
        return (base_tuple, (self.validator_index, self.is_exit_or_blocknumber))

    def serialize(self) -> dict[str, Any]:
        return super().serialize() | {'validator_index': self.validator_index, 'is_exit': self.is_exit_or_blocknumber}  # noqa: E501

    @classmethod
    def deserialize_from_db(cls: type['EthWithdrawalEvent'], entry: tuple) -> 'EthWithdrawalEvent':
        entry = cast(ETH_STAKING_EVENT_DB_TUPLE_READ, entry)
        amount = deserialize_fval(entry[3], 'amount', 'eth withdrawal event')
        usd_value = deserialize_fval(entry[4], 'usd_value', 'eth withdrawal event')
        return cls(
            identifier=entry[0],
            timestamp=TimestampMS(entry[1]),
            balance=Balance(amount, usd_value),
            withdrawal_address=entry[2],  # type: ignore  # exists for these events
            validator_index=entry[6],
            is_exit=bool(entry[7]),
        )

    @classmethod
    def deserialize(cls: type['EthWithdrawalEvent'], data: dict[str, Any]) -> 'EthWithdrawalEvent':
        base_data = cls._deserialize_base_history_data(data)
        try:
            validator_index = data['validator_index']
            withdrawal_address = deserialize_evm_address(data['location_label'])
            is_exit = data['is_exit']
        except KeyError as e:
            raise DeserializationError(f'Did not find expected withdrawal event key {str(e)}') from e  # noqa: E501

        if not isinstance(validator_index, int):
            raise DeserializationError(f'Found non-int validator index {validator_index}')

        return cls(
            timestamp=base_data['timestamp'],
            balance=base_data['balance'],
            validator_index=validator_index,
            withdrawal_address=withdrawal_address,
            is_exit=is_exit,
        )

    # -- Methods of AccountingEventMixin

    @staticmethod
    def get_accounting_event_type() -> AccountingEventType:
        return AccountingEventType.HISTORY_EVENT

    def should_ignore(self, ignored_ids_mapping: dict[ActionType, set[str]]) -> bool:
        return False  # TODO: Same question on ignoring as general HistoryEvent

    def process(
            self,
            accounting: 'AccountingPot',
            events_iterator: Iterator['AccountingEventMixin'],  # pylint: disable=unused-argument
    ) -> int:
        profit_amount = self.balance.amount
        if self.balance.amount >= 32:
            profit_amount = 32 - self.balance.amount

        # TODO: This is hacky and does not cover edge case where people mistakenly
        # double deposited for a validator. We can and should combine deposit and
        # withdrawal processing by querying deposits for that validator index.
        # saving pubkey and validator index for deposits.

        name = 'Exit' if bool(self.is_exit_or_blocknumber) else 'Withdrawal'
        accounting.add_acquisition(
            event_type=AccountingEventType.HISTORY_EVENT,
            notes=f'{name} of {self.balance.amount} ETH from validator {self.validator_index}. Only {profit_amount} is profit',  # noqa: E501
            location=self.location,
            timestamp=self.get_timestamp_in_sec(),
            asset=self.asset,
            amount=profit_amount,
            taxable=True,
        )
        return 1


class EthBlockEvent(EthStakingEvent):
    """An ETH block production/MEV event"""

    def __init__(
            self,
            validator_index: int,
            timestamp: TimestampMS,
            balance: Balance,
            fee_recipient: ChecksumEvmAddress,
            block_number: int,
            is_mev_reward: bool,
            identifier: Optional[int] = None,
    ) -> None:

        if is_mev_reward:
            sequence_index = 1
            event_subtype = HistoryEventSubType.MEV_REWARD
            name = 'mev reward'
        else:
            sequence_index = 0
            event_subtype = HistoryEventSubType.BLOCK_PRODUCTION
            name = 'block reward'

        super().__init__(
            event_identifier=f'evm_1_block_{block_number}',
            sequence_index=sequence_index,
            timestamp=timestamp,
            event_type=HistoryEventType.STAKING,
            event_subtype=event_subtype,
            validator_index=validator_index,
            balance=balance,
            location_label=fee_recipient,
            is_exit_or_blocknumber=block_number,
            notes=f'Validator {validator_index} produced block {block_number} with {balance.amount} ETH going to {fee_recipient} as the {name}',  # noqa: E501
        )

    def __repr__(self) -> str:
        return f'EthBlockEvent({self.validator_index=}, {self.timestamp=}, block_number={self.is_exit_or_blocknumber}, {self.event_subtype=})'  # noqa: E501

    def serialize_for_db(self) -> tuple[HISTORY_EVENT_DB_TUPLE_WRITE, tuple[int, int]]:
        base_tuple = self._serialize_base_tuple_for_db(HistoryBaseEntryType.ETH_BLOCK_EVENT)
        return (base_tuple, (self.validator_index, self.is_exit_or_blocknumber))

    def serialize(self) -> dict[str, Any]:
        return super().serialize() | {'validator_index': self.validator_index, 'block_number': self.is_exit_or_blocknumber}  # noqa: E501

    @classmethod
    def deserialize_from_db(cls: type['EthBlockEvent'], entry: tuple) -> 'EthBlockEvent':
        entry = cast(ETH_STAKING_EVENT_DB_TUPLE_READ, entry)
        amount = deserialize_fval(entry[3], 'amount', 'eth block event')
        usd_value = deserialize_fval(entry[4], 'usd_value', 'eth block event')
        return cls(
            identifier=entry[0],
            timestamp=TimestampMS(entry[1]),
            balance=Balance(amount, usd_value),
            fee_recipient=entry[2],  # type: ignore  # exists for these events
            validator_index=entry[6],
            block_number=entry[7],
            is_mev_reward=entry[5] == HistoryEventSubType.MEV_REWARD.serialize(),
        )

    @classmethod
    def deserialize(cls: type['EthBlockEvent'], data: dict[str, Any]) -> 'EthBlockEvent':
        base_data = cls._deserialize_base_history_data(data)
        try:
            validator_index = data['validator_index']
            fee_recipient = deserialize_evm_address(data['location_label'])
            block_number = data['block_number']
        except KeyError as e:
            raise DeserializationError(f'Did not find expected eth block event key {str(e)}') from e  # noqa: E501

        if not isinstance(validator_index, int):
            raise DeserializationError(f'Found non-int validator index {validator_index}')

        return cls(
            timestamp=base_data['timestamp'],
            balance=base_data['balance'],
            validator_index=validator_index,
            fee_recipient=fee_recipient,
            block_number=block_number,
            is_mev_reward=base_data['event_subtype'] == HistoryEventSubType.MEV_REWARD.serialize(),
        )

    # -- Methods of AccountingEventMixin

    @staticmethod
    def get_accounting_event_type() -> AccountingEventType:
        return AccountingEventType.HISTORY_EVENT

    def should_ignore(self, ignored_ids_mapping: dict[ActionType, set[str]]) -> bool:
        return False  # TODO: Same question on ignoring as general HistoryEvent

    def process(
            self,
            accounting: 'AccountingPot',
            events_iterator: Iterator['AccountingEventMixin'],  # pylint: disable=unused-argument
    ) -> int:
        with accounting.database.conn.read_ctx() as cursor:
            accounts = accounting.database.get_blockchain_accounts(cursor)

        if self.location_label not in accounts.eth:
            return 1  # fee recipient not tracked. So we do not add it in accounting

        if self.event_subtype == HistoryEventSubType.MEV_REWARD:
            name = 'Mev reward'
        else:
            name = 'Block reward'

        accounting.add_acquisition(
            event_type=AccountingEventType.HISTORY_EVENT,
            notes=f'{name} of {self.balance.amount} for block {self.is_exit_or_blocknumber}',
            location=self.location,
            timestamp=self.get_timestamp_in_sec(),
            asset=self.asset,
            amount=self.balance.amount,
            taxable=True,
        )
        return 1