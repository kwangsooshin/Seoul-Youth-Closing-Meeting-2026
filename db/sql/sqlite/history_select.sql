SELECT h.id, h.prize_id, p.rank AS prize_rank, COALESCE(p.name, '') AS prize_name,
       h.drawn_number, h.status, h.created_at
FROM draw_history h
JOIN prizes p ON p.id = h.prize_id
