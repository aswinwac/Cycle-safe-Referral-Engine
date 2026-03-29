import asyncio
import httpx
import random
import string
from uuid import uuid4

API_URL = "http://localhost:8000/api/v1"

def random_string(length=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))

async def register_user(client, username, email, referral_code=None):
    payload = {
        "email": email,
        "username": username,
        "password": "Password123!",
        "referral_code": referral_code
    }
    response = await client.post(f"{API_URL}/users/register", json=payload)
    if response.status_code == 201:
        return response.json()["data"]["user"]
    print(f"Failed to register {username}: {response.text}")
    return None

async def seed_data():
    async with httpx.AsyncClient() as client:
        print("Waiting for API to be available...")
        for _ in range(10):
            try:
                resp = await client.get(f"{API_URL}/health")
                if resp.status_code == 200:
                    break
            except httpx.ConnectError:
                await asyncio.sleep(2)
        else:
            print("API not reachable.")
            return

        print("API is up! Seeding data...")
        
        # User 1 (Root)
        user1 = await register_user(client, f"user1_{random_string(4)}", f"user1_{random_string(4)}@example.com")
        if not user1:
             return
        print(f"Created User 1: {user1['username']} (Ref Code: {user1['referral_code']})")

        # User 2 (Referred by User 1)
        user2 = await register_user(client, f"user2_{random_string(4)}", f"user2_{random_string(4)}@example.com", user1["referral_code"])
        if user2:
            print(f"Created User 2: {user2['username']} (referred by User 1)")

        # User 3 (Referred by User 2)
        if user2:
            user3 = await register_user(client, f"user3_{random_string(4)}", f"user3_{random_string(4)}@example.com", user2["referral_code"])
            if user3:
                print(f"Created User 3: {user3['username']} (referred by User 2)")

        print("Data Seeding Complete! View the dashboard to see metrics.")

if __name__ == "__main__":
    asyncio.run(seed_data())
