
from typing import Optional, Any
from aiohttp import web
from navigator.views import BaseView
from parrot.interfaces.documentdb import DocumentDb

class DocumentView(BaseView):
    """
    DocumentView.
    
    REST API for DocumentDB operations (Fire-and-Forget / CRUD).
    
    Supported Methods:
    - GET: Query documents.
    - PUT: Insert new document.
    - POST: Update existing document.
    - PATCH: Partial update of a document.
    - DELETE: Delete documents.
    """
    
    async def _get_db(self, bucket: Optional[str] = None) -> DocumentDb:
        """Helper to get a configured DocumentDb instance."""
        # Note: DocumentDb context manager handles connection
        return DocumentDb(database=bucket)

    async def get(self):
        """
        Query documents from a collection.
        
        URI: /api/v1/data/{collection}
        Params:
            bucket: Optional database name.
            filter: JSON string for query filter.
            limit: Optional limit.
        """
        collection = self.request.match_info.get('collection')
        params = self.get_arguments()
        bucket = params.get('bucket')
        filter_str = params.get('filter')
        limit = params.get('limit')
        
        query = {}
        if filter_str:
            try:
                import json
                query = json.loads(filter_str)
            except Exception:
                return self.critical(
                    response={"message": "Invalid filter format. Expected JSON."},
                    status=400
                )
                
        if limit:
            try:
                limit = int(limit)
            except ValueError:
                limit = 100

        try:
            db = await self._get_db(bucket)
            async with db:
                results = await db.read(collection, query=query, limit=limit)
                return self.json_response(results)
        except Exception as e:
            return self.critical(
                response={"message": f"Error querying collection {collection}: {e}"},
                status=500
            )

    async def put(self):
        """
        Insert a new document.
        
        Method: PUT
        Payload:
            bucket: Optional database name.
            data: Document to insert.
            
        Returns: 203 Non-Authoritative Information (as requested)
        """
        collection = self.request.match_info.get('collection')
        try:
            payload = await self.request.json()
        except Exception:
            return self.critical(
                response={"message": "Invalid JSON payload."},
                status=400
            )
            
        bucket = payload.get('bucket')
        data = payload.get('data')
        
        if not data:
            return self.critical(
                response={"message": "Missing 'data' in payload."},
                status=400
            )

        try:
            db = await self._get_db(bucket)
            async with db:
                # Check if it exists if _id is provided? 
                # User req: "de existir el registro, se emite un warning de 'registro ya existe'"
                # Asyncdb insert usually fails if _id exists.
                # But we can check specifically if user provided an ID or unique key.
                # For now, let's try insert and catch DuplicateKeyError if applicable.
                try:
                   res = await db.write(collection, data)
                   return self.json_response(
                       {"message": "Document inserted", "result": res},
                       status=203
                   )
                except Exception as e:
                     # Check if it is a duplicate key error (generic check)
                     if "Duplicate" in str(e) or "E11000" in str(e):
                          return self.json_response(
                              {"message": "Warning: Record already exists.", "error": str(e)},
                              status=409 # Conflict, but user said "warning". 409 is appropriate for exists.
                          )
                     request_id = self.request.headers.get('X-Request-ID', '')
                     return self.critical(
                         response={"message": f"Error inserting document: {e}", "request_id": request_id},
                         status=500
                     )

        except Exception as e:
             return self.critical(
                response={"message": f"System Error: {e}"},
                status=500
            )

    async def post(self):
        """
        Update an existing document (Full Update / Edit).
        
        Method: POST
        Payload:
            bucket: Optional database name.
            filter: Filter to find the document.
            data: New data.
            
        Returns: 202 Accepted
        """
        collection = self.request.match_info.get('collection')
        try:
            payload = await self.request.json()
        except Exception:
             return self.critical(
                response={"message": "Invalid JSON payload."},
                status=400
            )
            
        bucket = payload.get('bucket')
        filter_query = payload.get('filter')
        data = payload.get('data')
        
        if not filter_query or not data:
             return self.critical(
                response={"message": "Missing 'filter' or 'data'."},
                status=400
            )

        try:
            db = await self._get_db(bucket)
            async with db:
                # Check existence
                exists = await db.exists(collection, filter_query)
                if not exists:
                     return self.error(
                         response={"message": "Document not found."},
                         status=404
                     )
                
                # Update (Replace or Update?)
                # User says "se edita un registro". Usually POST/Update implies modification.
                # DocumentDb.update takes $set operators usually in MongoDB.
                # If 'data' is raw dict, we might need to wrap in '$set' if not present,
                # OR user sends MongoDB update operators.
                # User requirement: "se edita un registro ya existente"
                # Let's assume 'data' contains the update operators (like $set) OR is the new doc.
                # Safest is to use $set if not present.
                update_data = data
                if not any(k.startswith('$') for k in data.keys()):
                     update_data = {"$set": data}
                
                await db.update(collection, filter_query, update_data)
                return self.json_response(
                    {"message": "Accepted"},
                    status=202
                )
        except Exception as e:
             return self.critical(
                response={"message": f"Error updating document: {e}"},
                status=500
            )

    async def patch(self):
        """
        Partial Update.
        
        Method: PATCH
        Payload:
            bucket: Optional database name.
            filter: Filter to identify doc.
            data: Fields to update.
        """
        return await self.post() # Logic is same as POST for MongoDB usually ($set)

    async def delete(self):
        """
        Delete documents.
        
        Method: DELETE
        Payload:
            bucket: Optional database name.
            filter: Filter to identify docs.
        """
        collection = self.request.match_info.get('collection')
        
        # DELETE usually doesn't have body in some clients, but user req says "basado en un criterio de filtrado".
        # We can accept query string 'filter' for DELETE as standard practice,
        # OR JSON body. Aiohttp allows body in DELETE.
        
        try:
            payload = await self.request.json()
            bucket = payload.get('bucket')
            filter_query = payload.get('filter')
        except Exception:
             # Fallback to query params
             params = self.get_arguments()
             bucket = params.get('bucket')
             filter_str = params.get('filter')
             if filter_str:
                 try:
                     import json
                     filter_query = json.loads(filter_str)
                 except:
                     filter_query = None
             else:
                 filter_query = None

        if not filter_query:
            return self.critical(
                response={"message": "Missing 'filter'. Safety check prevented delete all."},
                status=400
            )

        try:
            db = await self._get_db(bucket)
            async with db:
                 res = await db.delete(collection, filter_query)
                 return self.json_response(
                     {"message": "Deleted", "result": res}
                 )
        except Exception as e:
             return self.critical(
                response={"message": f"Error deleting document: {e}"},
                status=500
            )
