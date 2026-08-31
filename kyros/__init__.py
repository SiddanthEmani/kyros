"""kyros — Bay Area event feed builder.

Scrapes several event sources (Luma, Ticketmaster, Funcheap),
classifies each event into categories (ai / edm / concert / free /
community), ranks with a San Jose–weighted score, and writes a combined
iCalendar feed plus per-category feeds.
"""

__all__ = ["pipeline"]
