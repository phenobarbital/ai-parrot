from datamodel import BaseModel
from navigator.views import ModelView
from .models import ADUser, ADPeople


class ADUserHandler(ModelView):
    model: BaseModel = ADUser
    pk: str = 'people_id'


class ADPeopleHandler(ModelView):
    model: BaseModel = ADPeople
    pk: str = 'people_id'
