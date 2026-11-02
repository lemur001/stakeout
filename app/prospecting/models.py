from pydantic import Field, field_validator, model_validator
from ..models import Strict, Campaign
from ..core import public_url

class Seed(Strict):
    name: str=Field(min_length=2,max_length=200)
    website: str=Field(default='',max_length=2000)
    source_url: str=Field(max_length=2000)
    ein: str=Field(default='',pattern=r'^(\d{9})?$')
    @field_validator('source_url','website')
    @classmethod
    def url(cls,v):return public_url(v,required=False)
    @model_validator(mode='after')
    def source(self):
        if not self.source_url:raise ValueError('A source URL is required for a seed.')
        return self

class HuntInput(Strict):
    city_id: str
    campaign: Campaign='rebuild'
    radius_miles: float=Field(default=10,ge=1,le=50)
    center_zip: str=Field(default='',pattern=r'^(\d{5})?$')
    max_revenue: int=Field(default=500000,ge=0,le=100000000)
    max_candidates: int=Field(default=100,ge=1,le=1000)
    types: list[str]=Field(default_factory=lambda:['service','history','civic','veterans','arts'],min_length=1,max_length=17)
    recent_only: bool=True
    use_irs: bool=True
    include_existing: bool=True
    use_web: bool=False
    use_backlinks: bool=False
    budget_cents: int=Field(default=0,ge=0,le=10000)
    paid_approved: bool=False
    rights_acknowledged: bool=False
    seeds: list[Seed]=Field(default_factory=list,max_length=100)
    @field_validator('types')
    @classmethod
    def known(cls,v):
        from .taxonomy import TYPE_LABEL
        if set(v)-set(TYPE_LABEL):raise ValueError('Unknown organization type.')
        return list(dict.fromkeys(v))
    @model_validator(mode='after')
    def scope(self):
        if not self.use_irs and not self.include_existing and not self.seeds:raise ValueError('Choose an inventory source or add sourced organizations.')
        if (self.use_web or self.use_backlinks) and (not self.paid_approved or not self.budget_cents):
            raise ValueError('Paid search and backlink checks require explicit approval and a budget.')
        return self
