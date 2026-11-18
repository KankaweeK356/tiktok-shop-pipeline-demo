# LOCAL_REAL_SOURCE_TEST — ไม่ใช่ Production Evidence
ไฟล์ในโฟลเดอร์นี้สร้างโดย worker จริงขณะรันเทส Journey Jan→Oct (`tests/test_dq_recovery_postgres.py`) กับ **ข้อมูล Source Final จริง** แต่บน **ฐานข้อมูลชั่วคราวในเครื่อง** (ไม่ใช่ Neon Production)
ทุก summary ระบุ `"data_origin": "LOCAL_REAL_SOURCE_TEST"` ยังไม่มี Production Evidence เพราะยังไม่ได้ deploy
