import asyncio
import ComunicatorServices

address = "ipc:///tmp/libmtcmaster.sock"
command = {'cmd': 'play'}


async def main():
    await ComunicatorServices.Comunicator(address).send_request(command)

if __name__ == "__main__":
    asyncio.run(main())

