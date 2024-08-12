"""
Data Management for Bots.
"""
from asyncdb.exceptions import NoDataFound, DriverError
from querysource.datasources.drivers.rethink import rethink_default
from navigator.views import FormModel
from ..utils.models import BotData
from ...interfaces import DBInterface

class DataManagement(DBInterface, FormModel):
    """
    Managing Data to be inserted into Vector Databases.
    """
    model = BotData
    path: str = '/api/v1/bot_management/data'

    async def get_rethink(self):
        params = rethink_default.params()
        return self.get_database('rethink', params=params)

    async def _get_form(self, args, qp, fields):
        """Get Form information."""
        bot = args.get('id', None)
        async with await self.get_rethink() as conn:
            await conn.use('navigator')
            filter = {}
            if bot:
                filter= {
                    "chatbot_id": bot
                }
                try:
                    result = await conn.fetch_all(
                        'chatbots_data',
                        filter=filter
                    )
                except NoDataFound:
                    return self.json_response(
                        status=204
                    )
            return self.json_response(
                result, status=200
            )

    async def put(self):
        """
        Creating a new data-store record.
        """
        data = await self.validate_payload()
        args = self.get_arguments()
        # unique field is ['chatbot_id', 'source_type', 'version']
        bot = args.get('id', data.chatbot_id)
        filter = {
            'chatbot_id': str(bot),
            'source_type': data.source_type,
            'version': data.version
        }
        tbl = data.Meta.name
        exists = False
        async with await self.get_rethink() as conn:
            await conn.use('navigator')
            try:
                result = await conn.fetch_one(
                    table=tbl,
                    filter=filter
                )
                if result:
                    exists = True
            except NoDataFound:
                exists = False
            if exists is False:
                try:
                    state = await conn.insert(
                        tbl, data.to_dict(), on_conflict='replace'
                    )
                    return self.json_response(
                        response={
                            "message": "Bot data inserted",
                            "state": state,
                        },
                        status=203
                    )
                except DriverError as exc:
                    return self.error(
                        response={
                            "error": "unable to insert RT data",
                            "exception": str(exc)
                        },
                        status=400
                    )
            else:
                data.version += data.version
                try:
                    state = await conn.update(
                        tbl, data.to_dict(), filter=filter, return_changes=True
                    )
                    return self.json_response(
                        response={
                            "message": "Bot data updated",
                            "state": state,
                        },
                        status=202
                    )
                except DriverError as exc:
                    return self.error(
                        response={
                            "error": "unable to insert RT data",
                            "exception": str(exc)
                        },
                        status=400
                    )

    async def patch(self):
        """
        Patching (updating) existing data.
        """
        # data = await self.validate_payload()
        data = await self.json_data()
        args = self.get_arguments()
        # unique field is ['chatbot_id', 'source_type', 'version']
        bot = args.get('id', data['chatbot_id'])
        try:
            filter = {
                'chatbot_id': str(bot),
                'source_type': data['source_type'],
                'version': data['version']
            }
        except KeyError:
            return self.error(
                response={
                    "error": "Invalid data for Data Filtering"
                },
                status=400
            )
        tbl = 'chatbots_data'
        async with await self.get_rethink() as conn:
            await conn.use('navigator')
            try:
                result = await conn.fetch_one(
                    table=tbl,
                    filter=filter
                )
                if result:
                    # update existing:
                    for k,v in data.items():
                        result[k] = v
                    try:
                        state = await conn.update(
                            tbl, result, filter=filter, return_changes=True
                        )
                        return self.json_response(
                            response={
                                "message": "Bot data updated",
                                "state": state,
                            },
                            status=202
                        )
                    except DriverError as exc:
                        return self.error(
                            response={
                                "error": "unable to Update RT data",
                                "exception": str(exc)
                            },
                            status=400
                        )
            except NoDataFound:
                return self.error(
                    response={
                        "error": f"Data not Found for {filter}",
                    },
                    status=400
                )

    async def delete(self):
        """
        Remove a data-store record
        """
        data = await self.validate_payload()
        args = self.get_arguments()
        # unique field is ['chatbot_id', 'source_type', 'version']
        bot = args.get('id', data.chatbot_id)
        filter = {
            'chatbot_id': str(bot),
            'source_type': data.source_type,
            'version': data.version
        }
        tbl = data.Meta.name
        async with await self.get_rethink() as conn:
            await conn.use('navigator')
            try:
                result = await conn.fetch_one(
                    table=tbl,
                    filter=filter
                )
                if result:
                    state = await conn.delete(
                        table=tbl,
                        filter=filter,
                        return_changes=True
                    )
                    return self.json_response(
                        response={
                            "message": "Bot data deleted",
                            "state": state,
                        },
                        status=202
                    )
            except NoDataFound:
                return self.error(
                    response={
                        "error": f"Data not Found for {filter}",
                    },
                    status=400
                )
