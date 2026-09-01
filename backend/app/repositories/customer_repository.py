"""Customer persistence — mostly a plain CRUD repository; the one non-trivial bit is
find-or-create by phone/email, since Razorpay payloads don't always carry a stable
`razorpay_contact_id`.
"""

from sqlalchemy import select

from app.domain.models.customer import Customer
from app.repositories.base_repository import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    model = Customer

    async def get_by_razorpay_contact_id(self, razorpay_contact_id: str) -> Customer | None:
        result = await self.session.execute(
            select(Customer).where(Customer.razorpay_contact_id == razorpay_contact_id)
        )
        return result.scalar_one_or_none()

    async def get_by_phone_or_email(self, *, phone: str | None, email: str | None) -> Customer | None:
        if not phone and not email:
            return None
        query = select(Customer)
        if phone:
            query = query.where(Customer.phone == phone)
        elif email:
            query = query.where(Customer.email == email)
        result = await self.session.execute(query.limit(1))
        return result.scalar_one_or_none()
