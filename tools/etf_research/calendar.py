"""2026 SSE calendar: https://www.sse.com.cn/disclosure/dealinstruc/closed"""
from datetime import date
CLOSED=set()
for month,start,end in [(1,1,3),(2,15,23),(4,4,6),(5,1,5),(6,19,21),(9,25,27),(10,1,7)]:
    CLOSED.update(date(2026,month,d) for d in range(start,end+1))
def is_session(day):
    if day.year!=2026:raise ValueError('calendar outside verified 2026 range')
    return day.weekday()<5 and day not in CLOSED
