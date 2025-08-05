from typing import Optional, List
from datetime import datetime, timedelta
from uuid import UUID
from datamodel.types import Text
from asyncdb.models import Column, Model
from navigator_auth.conf import AUTH_DB_SCHEMA, AUTH_USERS_VIEW


class User(Model):
    """Basic User notation."""

    user_id: int = Column(
        required=False,
        primary_key=True,
        db_default="auto"
    )
    first_name: str
    last_name: str
    display_name: str
    email: str = Column(required=False, max=254)
    alt_email: str = Column(required=False, max=254)
    password: str = Column(required=False, max=128)
    last_login: datetime = Column(required=False)
    username: str = Column(required=False)
    is_superuser: bool = Column(required=True, default=False)
    is_active: bool = Column(required=True, default=True)
    is_new: bool = Column(required=True, default=True)
    is_staff: bool = Column(required=False, default=True)
    title: str = Column(equired=False, max=90)
    avatar: str = Column(max=512)
    associate_id: str = Column(required=False)
    associate_oid: str = Column(required=False)
    department_code: str = Column(required=False)
    job_code: str = Column(required=False)
    position_id: str = Column(required=False)
    group_id: list = Column(required=False)
    groups: list = Column(required=False)
    program_id: list = Column(required=False)
    programs: list = Column(required=False)
    start_date: datetime = Column(required=False)
    birthday: str = Column(required=False)
    worker_type: str = Column(required=False)
    created_at: datetime = Column(required=False)

    def birth_date(self):
        if self.birthday:
            _, month, day = self.birthday.split('-')
            # Get the current year
            current_year = datetime.now().year
            # Create a new date string with the current year
            new_date_str = f"{current_year}-{month}-{day}"
            # Convert the new date string to a datetime object
            return datetime.strptime(new_date_str, "%Y-%m-%d").date()
        return None

    def employment_duration(self):
        if not self.start_date:
            return None, None, None
        # Get today's date
        today = datetime.now().date()
        # employment:
        employment = self.start_date

        # Calculate the difference in years, months, days
        years = today.year - employment.year
        months = today.month - employment.month
        days = today.day - employment.day

        # Adjust for cases where the current month is before the start month
        if months < 0:
            years -= 1
            months += 12

        # Adjust for cases where the current day
        # is before the start day in the month
        if days < 0:
            # Subtract one month and calculate days based on the previous month
            months -= 1
            if months < 0:
                years -= 1
                months += 12
            # Calculate the last day of the previous month
            last_day_of_prev_month = (
                today.replace(day=1) - timedelta(days=1)
            ).day
            days += last_day_of_prev_month

        # Adjust months and years again if necessary
        if months < 0:
            years -= 1
            months += 12

        return years, months, days

    class Meta:
        driver = "pg"
        name = AUTH_USERS_VIEW
        schema = AUTH_DB_SCHEMA
        description = 'View Model for getting Users.'
        strict = True
        frozen = False


class UserIdentity(Model):

    identity_id: UUID = Column(
        required=False,
        primary_key=True,
        db_default="auto",
        repr=False
    )
    display_name: str = Column(required=False)
    title: str = Column(required=False)
    nickname: str = Column(required=False)
    email: str = Column(required=False)
    phone: str = Column(required=False)
    short_bio: Text = Column(required=False)
    avatar: str = Column(required=False)
    user_id: User = Column(required=False, repr=False)
    auth_provider: str = Column(required=False)
    auth_data: Optional[dict] = Column(required=False, repr=False)
    attributes: Optional[dict] = Column(required=False, repr=False)
    created_at: datetime = Column(
        required=False,
        default=datetime.now(),
        repr=False
    )

    class Meta:
        driver = "pg"
        name = "user_identities"
        description = 'Manage User Identities.'
        schema = AUTH_DB_SCHEMA
        strict = True

class ADUser(Model):
    """Active Directory Users."""
    people_id: UUID = Column(
        required=False,
        primary_key=True,
        db_default="auto",
        repr=False
    )
    username: str = Column(required=False)
    display_name: str = Column(required=False)
    given_name: str = Column(required=False)
    last_name: str = Column(required=False)
    phones: Optional[list] = Column(required=False)
    mobile: str = Column(required=False)
    job_title: str = Column(required=False)
    email: str = Column(required=False)
    office_location: str = Column(required=False)
    preferred_language: str = Column(required=False)
    associate_id: str = Column(required=False)
    associate_oid: str = Column(required=False)
    job_code_title: str = Column(required=False)
    position_id: str = Column(required=False)
    zammad_created: bool = Column(required=False, default=False)
    created_at: datetime = Column(
        required=False,
        default=datetime.now(),
        repr=False
    )

    class Meta:
        name = 'people'
        schema = 'troc'
        strict = True


class ADPeople(Model):
    """Active Directory Users."""
    people_id: UUID = Column(
        required=False,
        primary_key=True,
        db_default="auto",
        repr=False
    )
    user_id: int = Column(required=True)
    userid: UUID = Column(required=False)
    username: str = Column(required=False)
    display_name: str = Column(required=False)
    given_name: str = Column(required=False)
    last_name: str = Column(required=False)
    phones: Optional[list] = Column(required=False)
    mobile: str = Column(required=False)
    job_title: str = Column(required=False)
    email: str = Column(required=False)
    alt_email: str = Column(required=False)
    office_location: str = Column(required=False)
    preferred_language: str = Column(required=False)
    associate_id: str = Column(required=False)
    associate_oid: str = Column(required=False)
    job_code_title: str = Column(required=False)
    position_id: str = Column(required=False)
    created_at: datetime = Column(
        required=False,
        default=datetime.now(),
        repr=False
    )

    class Meta:
        name = 'vw_people'
        schema = 'troc'
        strict = True
