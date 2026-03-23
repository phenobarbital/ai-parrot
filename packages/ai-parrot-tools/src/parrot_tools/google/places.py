"""
Google Business Profile Tools.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from textblob import TextBlob
from navconfig.logging import logging
from .base import GoogleBaseTool

class GoogleBusinessToolArgs(BaseModel):
    """Arguments schema for Google Business Tool."""
    command: str = Field(
        ...,
        description=(
            "Command to execute: 'list_accounts', 'list_locations', "
            "'get_reviews', 'reply_review', 'delete_reply'"
        )
    )
    account_id: Optional[str] = Field(
        default=None,
        description="Account ID (required for list_locations if multiple accounts exist)"
    )
    location_id: Optional[str] = Field(
        default=None,
        description="Location ID (required for reviews operations)"
    )
    review_id: Optional[str] = Field(
        default=None,
        description="Review ID (required for reply_review)"
    )
    reply_text: Optional[str] = Field(
        default=None,
        description="Text content for the reply"
    )
    language: Optional[str] = Field(
        default="en",
        description="Language code for sentiment analysis and responses"
    )


class GoogleBusinessTool(GoogleBaseTool):
    """
    Tool for interacting with Google Business Profile API.
    
    Capabilities:
    - List Accounts and Locations
    - Read Reviews
    - Reply to Reviews
    - Sentiment Analysis of Reviews
    """
    
    name = "google_business"
    description = (
        "Manage Google Business Profile: list locations, read/reply to reviews, "
        "and analyze sentiment."
    )
    args_schema = GoogleBusinessToolArgs
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # We need the 'business' scope for this tool
        if 'business' not in self.scopes and 'all' not in self.scopes:
             self.scopes = ['https://www.googleapis.com/auth/business.manage']

    async def _execute_google_operation(
        self,
        client: Any,
        **kwargs
    ) -> Any:
        """Execute Google Business Profile operations."""
        command = kwargs.get('command')
        
        # Get the MyBusiness Business Information API service
        # Note: Google has split APIs. We might need 'mybusinessbusinessinformation' 
        # for accounts/locations and 'mybusinessqanda' or 'mybusinessreviews' for reviews.
        # aiogoogle discovery might need specific versions.
        # For simplicity in this implementation, we'll assume we can get the service 
        # or use a generic request method if aiogoogle supports it.
        
        # Since aiogoogle discovery can be tricky with the new split APIs, 
        # we might need to rely on `client.execute_api_call` wrappers or raw requests 
        # if the specific API definition isn't straightforward in the wrapper.
        
        # Verification: Google Business Profile API v4 is deprecated. 
        # New APIs:
        # - Google My Business Account Management API
        # - Google My Business Lodging API
        # - Google My Business Place Actions API
        # - Google My Business Notifications API
        # - Google My Business Verifications API
        # - Google My Business Business Information API
        # - Google My Business Q&A API
        # - Google My Business Performance API
        
        # For Reviews, we specifically need the "My Business Reviews API" 
        # (mybusinessreviews/v1).
        # For Accounts/Locations, we need "My Business Account Management API" 
        # (mybusinessaccountmanagement/v1) and "Business Information API" 
        # (mybusinessbusinessinformation/v1).
        
        if command == 'list_accounts':
            return await self._list_accounts(client)
        elif command == 'list_locations':
            return await self._list_locations(client, kwargs.get('account_id'))
        elif command == 'get_reviews':
            return await self._get_reviews(
                client, 
                kwargs.get('account_id'), 
                kwargs.get('location_id')
            )
        elif command == 'reply_review':
            return await self._reply_review(
                client,
                kwargs.get('account_id'),
                kwargs.get('location_id'),
                kwargs.get('review_id'),
                kwargs.get('reply_text')
            )
        else:
            raise ValueError(f"Unknown command: {command}")

    async def _list_accounts(self, client: Any) -> List[Dict[str, Any]]:
        """List all accounts for the authenticated user."""
        # service: mybusinessaccountmanagement v1
        try:
            # Using generic execute_api_call if possible, or discovering the service directly
            # The interface might need updating to support these specific new APIs via 
            # short names if they aren't standard.
            # Let's try to discover 'mybusinessaccountmanagement' 'v1'
            
            res = await client.execute_api_call(
                'mybusinessaccountmanagement', 'accounts', 'list', version='v1'
            )
            return res.get('accounts', [])
        except Exception as e:
            self.logger.error(f"Error listing accounts: {e}")
            raise

    async def _list_locations(self, client: Any, account_id: Optional[str]) -> List[Dict[str, Any]]:
        """List locations for a specific account."""
        if not account_id:
            # Try to fetch the first account if none provided
            accounts = await self._list_accounts(client)
            if not accounts:
                raise ValueError("No accounts found.")
            account_id = accounts[0]['name'] # Format: accounts/{accountId}
        
        # Ensure account_id format
        if not account_id.startswith('accounts/'):
            account_id = f"accounts/{account_id}"

        try:
            # service: mybusinessbusinessinformation v1
            res = await client.execute_api_call(
                'mybusinessbusinessinformation', 
                'accounts.locations', 
                'list', 
                parent=account_id,
                readMask="name,title,storeCode,latlng",
                version='v1'
            )
            return res.get('locations', [])
        except Exception as e:
            self.logger.error(f"Error listing locations: {e}")
            raise

    async def _get_reviews(
        self, 
        client: Any, 
        account_id: Optional[str], 
        location_id: str
    ) -> List[Dict[str, Any]]:
        """Fetch reviews and perform sentiment analysis."""
        # reviews are under mybusinessreviews API
        # resource name format: accounts/{accountId}/locations/{locationId}
        
        if not location_id:
            raise ValueError("location_id is required for fetching reviews")

        # Construct parent string
        # If location_id is full path, use it. Else validation is tricky without account_id.
        parent = location_id
        if not parent.startswith('accounts/'):
            if not account_id:
                 raise ValueError("account_id is required if location_id is not a full path")
            if not account_id.startswith('accounts/'):
                account_id = f"accounts/{account_id}"
            
            loc_part = location_id if location_id.startswith('locations/') else f"locations/{location_id}"
            parent = f"{account_id}/{loc_part}"

        try:
            res = await client.execute_api_call(
                'mybusinessreviews',
                'accounts.locations.reviews',
                'list',
                parent=parent,
                version='v1'
            )
            
            reviews = res.get('reviews', [])
            processed_reviews = []
            
            for review in reviews:
                comment = review.get('comment', '')
                sentiment = self._analyze_sentiment(comment)
                
                processed_reviews.append({
                    'reviewId': review.get('reviewId'),
                    'reviewer': review.get('reviewer'),
                    'starRating': review.get('starRating'),
                    'comment': comment,
                    'createTime': review.get('createTime'),
                    'updateTime': review.get('updateTime'),
                    'reviewReply': review.get('reviewReply'),
                    'sentiment': sentiment
                })
                
            return {
                'location': parent,
                'total_reviews': len(processed_reviews),
                'reviews': processed_reviews
            }
            
        except Exception as e:
            self.logger.error(f"Error fetching reviews: {e}")
            raise

    async def _reply_review(
        self,
        client: Any, 
        account_id: Optional[str],
        location_id: str,
        review_id: str,
        reply_text: str
    ) -> Dict[str, Any]:
        """Reply to a specific review."""
        if not reply_text:
            raise ValueError("reply_text is required")
            
        # Construct name: accounts/{accountId}/locations/{locationId}/reviews/{reviewId}
        # If review_id is already full path, utilize it check? 
        # Usually user passes bare IDs or we handle the construction.
        
        name = review_id
        if not name.startswith('accounts/'):
             # Construct full path
             if not location_id:
                 raise ValueError("location_id required to construct review path")
             
             parent = location_id
             if not parent.startswith('accounts/'):
                 if not account_id:
                      raise ValueError("account_id required")
                 if not account_id.startswith('accounts/'):
                     account_id = f"accounts/{account_id}"
                 
                 loc_part = location_id if location_id.startswith('locations/') else f"locations/{location_id}"
                 parent = f"{account_id}/{loc_part}"
             
             name = f"{parent}/reviews/{review_id}"

        try:
            res = await client.execute_api_call(
                'mybusinessreviews',
                'accounts.locations.reviews',
                'updateReply', # Method is updateReply for replies
                name=f"{name}/reply",
                json={'comment': reply_text},
                version='v1'
            )
            return {
                'status': 'success',
                'reply': res
            }
        except Exception as e:
            self.logger.error(f"Error replying to review: {e}")
            raise

    def _analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """
        Analyze sentiment of the review text.
        Returns polarity (-1.0 to 1.0) and subjectivity (0.0 to 1.0).
        """
        if not text:
            return {'polarity': 0.0, 'subjectivity': 0.0, 'assessment': 'neutral'}
            
        blob = TextBlob(text)
        polarity = blob.sentiment.polarity
        subjectivity = blob.sentiment.subjectivity
        
        assessment = 'neutral'
        if polarity > 0.1:
            assessment = 'positive'
        elif polarity < -0.1:
            assessment = 'negative'
            
        return {
            'polarity': round(polarity, 2),
            'subjectivity': round(subjectivity, 2),
            'assessment': assessment
        }
