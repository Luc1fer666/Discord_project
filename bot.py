import discord
import asyncio
import aiohttp
import os
import random
import traceback
import sys
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from config import *
from settings import *
import json
import urllib.request

################## START INIT #####################
client = discord.Client()
# [playing?, {players dict}, day?, [night start, day start], [night elapsed, day elapsed], first join, gamemode, {original roles amount}]
session = [False, {}, False, [0, 0], [timedelta(0), timedelta(0)], 0, '', {}]
PLAYERS_ROLE = None
ADMINS_ROLE = None
WEREWOLF_NOTIFY_ROLE = None
ratelimit_dict = {}
pingif_dict = {}
notify_me = []
stasis = {}
commands = {}
faftergame = None
starttime = datetime.now()
with open(NOTIFY_FILE, 'a+') as notify_file:
    notify_file.seek(0)
    notify_me = notify_file.read().split(',')

if os.path.isfile(STASIS_FILE):
    with open(STASIS_FILE, 'r') as stasis_file:
        stasis = json.load(stasis_file)
else:
    with open(STASIS_FILE, 'a+') as stasis_file:
        stasis_file.write('{}')

random.seed(datetime.now())

def get_jsonparsed_data(url):
    try:
        response = urllib.request.urlopen(url)
    except urllib.error.HTTPError:
        return None, None # url does not exist
    data = response.read().decode("utf-8")
    return json.loads(data), data
	
def load_language(language):
	file = 'lang/{}.json'.format(language)
	if not os.path.isfile(file):
		file = 'lang/en.json'
		print("Could not find language file {}.json, fallback on en.json".format(language))
	with open(file, 'r', encoding='utf-8') as f:
		return json.load(f)
		
lang = load_language(MESSAGE_LANGUAGE)

def cmd(name, perms, description, *aliases):
    def real_decorator(func):
        commands[name] = [func, perms, description.format(BOT_PREFIX)]
        for alias in aliases:
            if alias not in commands:
                commands[alias] = [func, perms, "```\nAlias for {0}{1}.```".format(BOT_PREFIX, name)]
            else:
                print("ERROR: Cannot assign alias {0} to command {1} since it is already the name of a command!".format(alias, name))
        return func
    return real_decorator

################### END INIT ######################

@client.event
async def on_ready():
    print('Logged in as')
    print(client.user.name)
    print(client.user.id)
    print('------')
    await log(1, 'on_ready triggered!')
    # [playing : True | False, players : {player id : [alive, role, action, template, other]}, day?, [datetime night, datetime day], [elapsed night, elapsed day], first join time, gamemode]
    for role in client.get_server(WEREWOLF_SERVER).role_hierarchy:
        if role.name == PLAYERS_ROLE_NAME:
            global PLAYERS_ROLE
            PLAYERS_ROLE = role
        if role.name == ADMINS_ROLE_NAME:
            global ADMINS_ROLE
            ADMINS_ROLE = role
        if role.name == WEREWOLF_NOTIFY_ROLE_NAME:
            global WEREWOLF_NOTIFY_ROLE
            WEREWOLF_NOTIFY_ROLE = role
    if PLAYERS_ROLE:
        await log(0, "Players role id: " + PLAYERS_ROLE.id)
    else:
        await log(3, "Could not find players role " + PLAYERS_ROLE_NAME)
    if ADMINS_ROLE:
        await log(0, "Admins role id: " + ADMINS_ROLE.id)
    else:
        await log(3, "Could not find admins role " + ADMINS_ROLE_NAME)
    if WEREWOLF_NOTIFY_ROLE:
        await log(0, "Werewolf Notify role id: " + WEREWOLF_NOTIFY_ROLE.id)
    else:
        await log(2, "Could not find Werewolf Notify role " + WEREWOLF_NOTIFY_ROLE_NAME)
    if PLAYING_MESSAGE:
        await client.change_presence(status=discord.Status.online, game=discord.Game(name=PLAYING_MESSAGE))

@client.event
async def on_resume():
    print("RESUMED")
    await log(1, "on_resume triggered!")
	
@client.event
async def on_message(message):
    if message.author.id in [client.user.id] + IGNORE_LIST or not client.get_server(WEREWOLF_SERVER).get_member(message.author.id):
        if not (message.author.id in ADMINS or message.author.id == OWNER_ID):
            return
    if await rate_limit(message):
        return

    if message.channel.is_private:
        await log(0, 'pm from ' + message.author.name + ' (' + message.author.id + '): ' + message.content)
        if session[0] and message.author.id in session[1]:
            if session[1][message.author.id][1] in WOLFCHAT_ROLES and session[1][message.author.id][0]:
                if not message.content.strip().startswith(BOT_PREFIX):
                    await wolfchat(message)

    if message.content.strip().startswith(BOT_PREFIX):
        # command
        command = message.content.strip()[len(BOT_PREFIX):].lower().split(' ')[0]
        parameters = ' '.join(message.content.strip().lower().split(' ')[1:])
        if has_privileges(1, message) or message.channel.id == GAME_CHANNEL or message.channel.is_private:
            await parse_command(command, message, parameters)
    elif message.channel.is_private:
        command = message.content.strip().lower().split(' ')[0]
        parameters = ' '.join(message.content.strip().lower().split(' ')[1:])
        await parse_command(command, message, parameters)

############# COMMANDS #############
@cmd('shutdown', [2, 2], "```\n{0}shutdown takes no arguments\n\nShuts down the bot. Owner-only.```")
async def cmd_shutdown(message, parameters):
    if parameters.startswith("-fstop"):
        await cmd_fstop(message, "-force")
    elif parameters.startswith("-stop"):
        await cmd_fstop(message, parameters[len("-stop"):])
    elif parameters.startswith("-fleave"):
        await cmd_fleave(message, 'all')
    await reply(message, "Shutting down...")
    await client.logout()

@cmd('ping', [0, 0], "```\n{0}ping takes no arguments\n\nTests the bot\'s responsiveness.```")
async def cmd_ping(message, parameters):
    msg = random.choice(lang['ping']).format(
        bot_nick=client.user.display_name, author=message.author.name, p=BOT_PREFIX)
    await reply(message, msg)

@cmd('eval', [2, 2], "```\n{0}eval <evaluation string>\n\nEvaluates <evaluation string> using Python\'s eval() function and returns a result. Owner-only.```")
async def cmd_eval(message, parameters):
    output = None
    parameters = ' '.join(message.content.split(' ')[1:])
    if parameters == '':
        await reply(message, commands['eval'][2].format(BOT_PREFIX))
        return
    try:
        output = eval(parameters)
    except:
        await reply(message, '```\n' + str(traceback.format_exc()) + '\n```')
        traceback.print_exc()
        return
    if asyncio.iscoroutine(output):
        output = await output
    await reply(message, '```py\n' + str(output) + '\n```')

@cmd('exec', [2, 2], "```\n{0}exec <exec string>\n\nExecutes <exec string> using Python\'s exec() function. Owner-only.```")
async def cmd_exec(message, parameters):
    parameters = ' '.join(message.content.split(' ')[1:])
    if parameters == '':
        await reply(message, commands['exec'][2].format(BOT_PREFIX))
        return
    old_stdout = sys.stdout
    redirected_output = sys.stdout = StringIO()
    try:
        exec(parameters)
    except Exception:
        await reply(message, '```py\n{}\n```'.format(traceback.format_exc()))
        return
    finally:
        sys.stdout = old_stdout
    output = str(redirected_output.getvalue())
    if output == '':
        output = ":thumbsup:"
    await client.send_message(message.channel, output)
	
@cmd('async', [2, 2], "```\n{0}async <code>\n\nExecutes <code> as a coroutine.```")
async def cmd_async(message, parameters, recursion=0):
    if parameters == '':
        await reply(message, commands['async'][2].format(PREFIX))
        return
    env = {'message' : message,
           'parameters' : parameters,
           'recursion' : recursion,
           'client' : client,
           'channel' : message.channel,
           'author' : message.author,
           'server' : message.server}
    env.update(globals())
    old_stdout = sys.stdout
    redirected_output = sys.stdout = StringIO()
    result = None
    exec_string = "async def _temp_exec():\n"
    exec_string += '\n'.join(' ' * 4 + line for line in parameters.split('\n'))
    try:
        exec(exec_string, env)
    except Exception:
        traceback.print_exc()
        result = traceback.format_exc()
    else:
        _temp_exec = env['_temp_exec']
        try:
            returnval = await _temp_exec()
            value = redirected_output.getvalue()
            if returnval == None:
                result = value
            else:
                result = value + '\n' + str(returnval)
        except Exception:
            traceback.print_exc()
            result = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
    await client.send_message(message.channel, "```py\n{}\n```".format(result))

@cmd('help', [0, 0], "```\n{0}help <command>\n\nCho biết thông tin về <command>. Try {0}list for a listing of commands.```")
async def cmd_help(message, parameters):
    if parameters == '':
        parameters = 'help'
    if parameters in commands:
        await reply(message, commands[parameters][2].format(BOT_PREFIX))
    else:
        await reply(message, 'No help found for command ' + parameters)

@cmd('list', [0, 0], "```\n{0}list không cần thêm cú pháp\n\nHiển thị danh sách lệnh. Thử {0}help <command> để biết chi tiết về 1 lệnh.```")
async def cmd_list(message, parameters):
    cmdlist = []
    for key in commands:
        if message.channel.is_private:
            if has_privileges(commands[key][1][1], message):
                cmdlist.append(key)
        else:
            if has_privileges(commands[key][1][0], message):
                cmdlist.append(key)
    await reply(message, "Available commands: {}".format(", ".join(sorted(cmdlist))))

@cmd('join', [0, 1], "```\n{0}join [<gamemode>]\n\nTham gia trò chơi nếu chưa bắt đầu. Vote cho [<gamemode>] nếu được hỏi.```", 'j')
async def cmd_join(message, parameters):
    if session[0]:
        return
    if message.author.id in stasis and stasis[message.author.id] > 0:
        await reply(message, "You are in stasis for **{}** game{}. Please do not break rules, idle out or use !leave during a game.".format(
                                stasis[message.author.id], '' if stasis[message.author.id] == 1 else 's'))
        return
    if len(session[1]) >= MAX_PLAYERS:
        await reply(message, random.choice(lang['maxplayers']).format(MAX_PLAYERS))
        return
    if message.author.id in session[1]:
        await reply(message, random.choice(lang['alreadyin']).format(message.author.name))
    else:
        session[1][message.author.id] = [True, '', '', [], []]
        if len(session[1]) == 1:
            client.loop.create_task(game_start_timeout_loop())
            await client.change_presence(game=client.get_server(WEREWOLF_SERVER).me.game, status=discord.Status.idle)
            await client.send_message(client.get_channel(GAME_CHANNEL), random.choice(lang['gamestart']).format(
                                            message.author.name, p=BOT_PREFIX))
        else:
            await client.send_message(message.channel, "**{}** tham gia và tăng số người chơi lên **{}**.".format(
                                                        message.author.name, len(session[1])))
        if parameters:
            await cmd_vote(message, parameters)
        #                            alive, role, action, [templates], [other]
        await client.add_roles(client.get_server(WEREWOLF_SERVER).get_member(message.author.id), PLAYERS_ROLE)
        await player_idle(message)

@cmd('leave', [0, 1], "```\n{0}leave không cần thêm cú pháp\n\nRời game đang chơi. Nếu thực sự cần rời thì hãy rời trước khi game bắt đầu chơi.```", 'q')
async def cmd_leave(message, parameters):
    if session[0] and message.author.id in list(session[1]) and session[1][message.author.id][0]:
        session[1][message.author.id][0] = False
        await client.send_message(client.get_channel(GAME_CHANNEL), random.choice(lang['leavedeath']).format(message.author.name, get_role(message.author.id, 'death')))
        await client.remove_roles(client.get_server(WEREWOLF_SERVER).get_member(message.author.id), PLAYERS_ROLE)
        if message.author.id in stasis:
            stasis[message.author.id] += QUIT_GAME_STASIS
        else:
            stasis[message.author.id] = QUIT_GAME_STASIS
        if session[0] and win_condition() == None:
            await check_traitor()
        await log(1, "{} ({}) QUIT DURING GAME".format(message.author.display_name, message.author.id))
    else:
        if message.author.id in session[1]:
            if session[0]:
                await reply(message, "wot?")
                return
            del session[1][message.author.id]
            await client.send_message(client.get_channel(GAME_CHANNEL), random.choice(lang['leavelobby']).format(message.author.name, len(session[1])))
            if len(session[1]) == 0:
                await client.change_presence(game=client.get_server(WEREWOLF_SERVER).me.game, status=discord.Status.online)
            await client.remove_roles(client.get_server(WEREWOLF_SERVER).get_member(message.author.id), PLAYERS_ROLE)
        else:
            await reply(message, random.choice(lang['notplayingleave']))

@cmd('fjoin', [1, 1], "```\n{0}fjoin <mentions of users>\n\nForces each <mention> to join the game.```")
async def cmd_fjoin(message, parameters):
    if session[0]:
        return
    if parameters == '':
        await reply(message, commands['fjoin'][2].format(BOT_PREFIX))
        return
    raw_members = parameters.split(' ')
    join_list = []
    for member in raw_members:
        if member.strip('<!@>').isdigit():
            join_list.append(member.strip('<!@>'))
        elif '-' in member:
            left = member.split('-')[0]
            right = member.split('-')[1]
            if left.isdigit() and right.isdigit():
                join_list += list(map(str, range(int(left), int(right) + 1)))
    if join_list == []:
        await reply(message, "ERROR: no valid mentions found")
        return
    join_msg = ""
    for member in sort_players(join_list):
        session[1][member] = [True, '', '', [], []]
        join_msg += "**" + get_name(member) + "** was forced to join the game.\n"
        if client.get_server(WEREWOLF_SERVER).get_member(member):
            await client.add_roles(client.get_server(WEREWOLF_SERVER).get_member(member), PLAYERS_ROLE)
    join_msg += "New player count: **{}**".format(len(session[1]))
    if len(session[1]) > 0:
        await client.change_presence(game=client.get_server(WEREWOLF_SERVER).me.game, status=discord.Status.idle)
    await client.send_message(message.channel, join_msg)
    await log(2, "{0} ({1}) used FJOIN {2}".format(message.author.name, message.author.id, parameters))

@cmd('fleave', [1, 1], "```\n{0}fleave <mentions of users | all>\n\nForces each <mention> to leave the game. If the parameter is all, removes all players from the game.```")
async def cmd_fleave(message, parameters):
    if parameters == '':
        await reply(message, commands['fleave'][2].format(BOT_PREFIX))
        return
    raw_members = parameters.split(' ')
    leave_list = []
    if parameters == 'all':
        leave_list = list(session[1])
    else:
        for member in raw_members:
            if member.strip('<!@>').isdigit():
                leave_list.append(member.strip('<!@>'))
            elif '-' in member:
                left = member.split('-')[0]
                right = member.split('-')[1]
                if left.isdigit() and right.isdigit():
                    leave_list += list(map(str, range(int(left), int(right) + 1)))
    if leave_list == []:
        await reply(message, "ERROR: no valid mentions found")
        return
    leave_msg = ""

    for member in sort_players(leave_list):
        if member in list(session[1]):
            if session[0]:
                session[1][member][0] = False
                leave_msg += "**" + get_name(member) + "** bị đẩy vào ngọn lửa, không khí thơm mùi mỡ khét của **" + get_role(member, 'death') + "**.\n"
            else:
                del session[1][member]
                leave_msg += "**" + get_name(member) + "** bị bắt phải rời trò chơi.\n"
            if client.get_server(WEREWOLF_SERVER).get_member(member):
                await client.remove_roles(client.get_server(WEREWOLF_SERVER).get_member(member), PLAYERS_ROLE)
    if not session[0]:
        leave_msg += "New player count: **{}**".format(len(session[1]))
        if len(session[1]) == 0:
            await client.change_presence(game=client.get_server(WEREWOLF_SERVER).me.game, status=discord.Status.online)
    await client.send_message(client.get_channel(GAME_CHANNEL), leave_msg)
    await log(2, "{0} ({1}) used FLEAVE {2}".format(message.author.name, message.author.id, parameters))
    if session[0] and win_condition() == None:
        await check_traitor()

@cmd('refresh', [1, 1], "```\n{0}refresh [<language file>]\n\nRefreshes the current language's language file from GitHub. Admin only.```")
async def cmd_refresh(message, parameters):
    global lang
    if parameters == '':
        parameters = MESSAGE_LANGUAGE
    url = "https://raw.githubusercontent.com/belguawhale/Discord-Werewolf/master/lang/{}.json".format(parameters)
    codeset = parameters
    temp_lang, temp_str = get_jsonparsed_data(url)
    if not temp_lang:
        await reply(message, "Could not refresh language {} from Github.".format(parameters))
        return
    with open('lang/{}.json'.format(parameters), 'w', encoding='utf-8') as f:
        f.write(temp_str)
    lang = temp_lang
    await reply(message, 'The messages with language code `' + codeset + '` have been refreshed from GitHub.')

@cmd('start', [0, 1], "```\n{0}start không cần thêm cú pháp\n\nBầu chọn bắt đầu game. Một game cần ít nhất " +\
                      str(MIN_PLAYERS) + " người chơi để bắt đầu.```")
async def cmd_start(message, parameters):
    if session[0]:
        return
    if message.author.id not in session[1]:
        await reply(message, random.choice(lang['notplayingstart']))
        return
    if len(session[1]) < MIN_PLAYERS:
        await reply(message, random.choice(lang['minplayers']).format(MIN_PLAYERS))
        return
    if session[1][message.author.id][1]:
        return
    session[1][message.author.id][1] = 'start'
    votes = len([x for x in session[1] if session[1][x][1] == 'start'])
    votes_needed = max(2, min(len(session[1]) // 4 + 1, 4))
    if votes < votes_needed:
        await client.send_message(client.get_channel(GAME_CHANNEL), "**{}** Đang muốn bắt đầu trò chơi. **{}** votes nữa để bắt đầu{}.".format(
                                  message.author.display_name, votes_needed - votes, '' if (votes_needed - votes == 1) else 's'))
    else:
        await run_game()
    if votes == 1:
        await start_votes(message.author.id)

@cmd('fstart', [1, 2], "```\n{0}fstart takes no arguments\n\nForces game to start.```")
async def cmd_fstart(message, parameters):
    if session[0]:
        return
    if len(session[1]) < MIN_PLAYERS:
        await reply(message, random.choice(lang['minplayers']).format(MIN_PLAYERS))
    else:
        await client.send_message(client.get_channel(GAME_CHANNEL), "**" + message.author.name + "** forced the game to start.")
        await log(2, "{0} ({1}) FSTART".format(message.author.name, message.author.id))
        await run_game()

@cmd('fstop', [1, 1], "```\n{0}fstop [<-force|reason>]\n\nForcibly stops the current game with an optional [<reason>]. Use {0}fstop -force if "
                      "bot errors.```")
async def cmd_fstop(message, parameters):
    msg = "Game forcibly stopped by **" + message.author.name + "**"
    if parameters == "":
        msg += "."
    elif parameters == "-force":
        if not session[0]:
            return
        msg += ". Here is some debugging info:\n```py\n{0}\n```".format(str(session))
        session[0] = False
        perms = client.get_channel(GAME_CHANNEL).overwrites_for(client.get_server(WEREWOLF_SERVER).default_role)
        perms.send_messages = True
        await client.edit_channel_permissions(client.get_channel(GAME_CHANNEL), client.get_server(WEREWOLF_SERVER).default_role, perms)
        for player in list(session[1]):
            del session[1][player]
            member = client.get_server(WEREWOLF_SERVER).get_member(player)
            if member:
                await client.remove_roles(member, PLAYERS_ROLE)
        session[3] = [0, 0]
        session[4] = [timedelta(0), timedelta(0)]
        session[6] = ''
        session[7] = {}
        await client.send_message(client.get_channel(GAME_CHANNEL), msg)
        return
    else:
        msg += " for reason: `" + parameters + "`."

    if not session[0]:
        await reply(message, "There is no currently running game!")
        return
    else:
        await log(2, "{0} ({1}) FSTOP {2}".format(message.author.name, message.author.id, parameters))
    await end_game(msg + '\n\n' + end_game_stats())

@cmd('sync', [1, 1], "```\n{0}sync takes no arguments\n\nSynchronizes all player roles and channel permissions with session.```")
async def cmd_sync(message, parameters):
    for member in client.get_server(WEREWOLF_SERVER).members:
        if member.id in session[1] and session[1][member.id][0]:
            if not PLAYERS_ROLE in member.roles:
                await client.add_roles(member, PLAYERS_ROLE)
        else:
            if PLAYERS_ROLE in member.roles:
                await client.remove_roles(member, PLAYERS_ROLE)
    perms = client.get_channel(GAME_CHANNEL).overwrites_for(client.get_server(WEREWOLF_SERVER).default_role)
    if session[0]:
        perms.send_messages = False
    else:
        perms.send_messages = True
    await client.edit_channel_permissions(client.get_channel(GAME_CHANNEL), client.get_server(WEREWOLF_SERVER).default_role, perms)
    await log(2, "{0} ({1}) SYNC".format(message.author.name, message.author.id))
    await reply(message, "Sync successful.")

@cmd('op', [1, 1], "```\n{0}op takes no arguments\n\nOps yourself if you are an admin```")
async def cmd_op(message, parameters):
    await log(2, "{0} ({1}) OP {2}".format(message.author.name, message.author.id, parameters))
    if parameters == "":
        await client.add_roles(client.get_server(WEREWOLF_SERVER).get_member(message.author.id), ADMINS_ROLE)
        await reply(message, ":thumbsup:")
    else:
        member = client.get_server(WEREWOLF_SERVER).get_member(parameters.strip("<!@>"))
        if member:
            if member.id in ADMINS:
                await client.add_roles(member, ADMINS_ROLE)
                await reply(message, ":thumbsup:")

@cmd('deop', [1, 1], "```\n{0}deop takes no arguments\n\nDeops yourself so you can play with the players ;)```")
async def cmd_deop(message, parameters):
    await log(2, "{0} ({1}) DEOP {2}".format(message.author.name, message.author.id, parameters))
    if parameters == "":
        await client.remove_roles(client.get_server(WEREWOLF_SERVER).get_member(message.author.id), ADMINS_ROLE)
        await reply(message, ":thumbsup:")
    else:
        member = client.get_server(WEREWOLF_SERVER).get_member(parameters.strip("<!@>"))
        if member:
            if member.id in ADMINS:
                await client.remove_roles(member, ADMINS_ROLE)
                await reply(message, ":thumbsup:")

@cmd('role', [0, 0], "```\n{0}role [<role | number of players | gamemode>] [<number of players>]\n\nNếu đưa ra tên một <role>, "
                     "cho biết thông tin về <role> đó. Nếu cho số lượng người chơi <number of players>, Cho biết số lượng mỗi thành phần "
                     "role for the specified <number of players> for the specified <gamemode>, defaulting to default. If "
                     "only a <gamemode> is given, displays a role guide for <gamemode>. "
                     "Nếu để trống, cho danh sách các vai.```", 'roles')
async def cmd_role(message, parameters):
	if parameters == "" and not session[0] or parameters == 'list':
        await reply(message, "Roles: " + ", ".join(sort_roles(roles)))
        return
    elif parameters == "" and session[0]:
        msg = "**{}** người chơi đang chơi **{}** gamemode:```\n".format(len(session[1]),
        'roles' if session[6].startswith('roles') else session[6])
        if session[6] in ('random',):
            msg += "!role không thể xài trong {} gamemode.\n```".format(session[6])
            await reply(message, msg)
            return

        game_roles = dict(session[7])

        msg += '\n'.join(["{}: {}".format(x, game_roles[x]) for x in sort_roles(game_roles)])
        msg += '```'
        await reply(message, msg)
        return
    elif _autocomplete(parameters, roles)[1] == 1:
        role = _autocomplete(parameters, roles)[0]
        await reply(message, "```\nTên vai: {}\nPhe: {}\nMiêu tả: {}\n```".format(role, roles[role][0], roles[role][2]))
        return
    params = parameters.split(' ')
    gamemode = 'default'
    num_players = -1
    choice, num = _autocomplete(params[0], gamemodes)
    if num == 1:
        gamemode = choice

    if params[0].isdigit():
        num_players = params[0]
    elif len(params) == 2 and params[1].isdigit():
        num_players = params[1]
    if num_players == -1:
        if len(params) == 2:
            if params[1] == 'table':
                # generate role table
                WIDTH = 20
                role_dict = gamemodes[gamemode]['roles']
                role_guide = "Bảng role cho chế độ **{}**:\n".format(gamemode)
                role_guide += "```\n" + " " * (WIDTH + 2)
                role_guide += ','.join("{}{}".format(' ' * (2 - len(str(x))), x) for x in range(gamemodes[gamemode]['min_players'], gamemodes[gamemode]['max_players'] + 1)) + '\n'
                role_guide += '\n'.join(role + ' ' * (WIDTH - len(role)) + ": " + repr(\
                role_dict[role][gamemodes[gamemode]['min_players'] - MIN_PLAYERS:gamemodes[gamemode]['max_players']]) for role in sort_roles(role_dict))
                role_guide += "\n```"
            elif params[1] == 'guide':
                # generate role guide
                role_dict = gamemodes[gamemode]['roles']
                prev_dict = dict((x, 0) for x in roles if x != 'villager')
                role_guide = 'Các role trong gamemode **{}**:\n'.format(gamemode)
                for i in range(gamemodes[gamemode]['max_players'] - MIN_PLAYERS + 1):
                    current_dict = {}
                    for role in sort_roles(roles):
                        if role == 'villager':
                            continue
                        if role in role_dict:
                            current_dict[role] = role_dict[role][i]
                        else:
                            current_dict[role] = 0
                    # compare previous and current
                    if current_dict == prev_dict:
                        # same
                        continue
                    role_guide += '**[{}]** '.format(i + MIN_PLAYERS)
                    for role in sort_roles(roles):
                        if role == 'villager':
                            continue
                        if current_dict[role] == 0 and prev_dict[role] == 0:
                            # role not in gamemode
                            continue
                        if current_dict[role] > prev_dict[role]:
                            # role increased
                            role_guide += role
                            if current_dict[role] > 1:
                                role_guide += " ({})".format(current_dict[role])
                            role_guide += ', '
                        elif prev_dict[role] > current_dict[role]:
                            role_guide += '~~{}'.format(role)
                            if prev_dict[role] > 1:
                                role_guide += " ({})".format(prev_dict[role])
                            role_guide += '~~, '
                    role_guide = role_guide.rstrip(', ') + '\n'
                    # makes a copy
                    prev_dict = dict(current_dict)
            else:
                role_guide = "Hãy chọn 1 trong 2 phụ lệnh: " + ', '.join(['guide', 'table'])
        else:
            role_guide = "Please choose one of the following for the third parameter: {}".format(', '.join(['guide', 'table']))
        await reply(message, role_guide)
    else:
        num_players = int(num_players)
        if num_players in range(gamemodes[gamemode]['min_players'], gamemodes[gamemode]['max_players'] + 1):
            if gamemode in ('random',):
                msg = "!role đã bị tắt trong **{}** gamemode.".format(gamemode)
            else:
                msg = "Vai của **{}** người chơi trong chế độ **{}**:```\n".format(num_players, gamemode)
                game_roles = get_roles(gamemode, num_players)
                msg += '\n'.join("{}: {}".format(x, game_roles[x]) for x in sort_roles(game_roles))
                msg += '```'
            await reply(message, msg)
        else:
            await reply(message, "Hãy chọn số người chơi trong khoảng " + str(gamemodes[gamemode]['min_players']) +\
            " and " + str(gamemodes[gamemode]['max_players']) + ".")

async def _send_role_info(player, sendrole=True):
    if session[0] and player in session[1]:
        member = client.get_server(WEREWOLF_SERVER).get_member(player)
        if member and session[1][player][0]:
            role = get_role(player, 'role')
            templates = get_role(player, 'templates')
            if member and session[1][player][0]:
                try:
                    if sendrole:
                        await client.send_message(member, "Vai của bạn là **" + role + "**. " + roles[role][2] + '\n')
                    living_players = [x for x in session[1] if session[1][x][0]]
                    living_players_string = ', '.join('**{}** ({})'.format(get_name(x), x) for x in living_players)
                    msg = ''
                    if roles[role][0] == 'wolf' and role != 'cultist':
                        living_players_string = ''
                        for plr in living_players:
                            temprole = get_role(plr, 'role')
                            temptemplates = get_role(plr, 'templates')
                            role_string = ''
                            if 'cursed' in temptemplates:
                                role_string += 'cursed '
                            if roles[temprole][0] == 'wolf' and temprole != 'cultist':
                                role_string += temprole
                            living_players_string += "**{}** ({})".format(get_name(plr), plr)
                            if role_string:
                                living_players_string += " (**{}**)".format(role_string.rstrip(' '))
                            living_players_string += ', '
                        living_players_string = living_players_string.rstrip(', ')
                    elif role == 'shaman':
                        if session[1][player][2] in totems:
                            totem = session[1][player][2]
                            msg += "Bạn có bùa **{0}**. {1}".format(totem.replace('_', ' '), totems[totem]) + '\n'
                    if role in ['wolf', 'werecrow', 'werekitten', 'traitor', 'sorcerer', 'harlot', 'seer',
                                'shaman', 'hunter', 'detective', 'crazed shaman']:
                        msg += "Living players: " + living_players_string + '\n\n'
                    if 'gunner' in templates:
                        msg += "Bạn có 1 khẩu súng lục và **{}** viên đạn{}. Xài lệnh `{}role gunner` để biết chi tiết.".format(
                            session[1][player][4].count('bullet'), '' if session[1][player][4].count('bullet') == 1 else 's', BOT_PREFIX)
                    if msg != '':
                        await client.send_message(member, msg)
                except discord.Forbidden:
                    await client.send_message(client.get_channel(GAME_CHANNEL), member.mention + ", bạn không thể chơi game nếu bạn chặn tôi :<")

@cmd('myrole', [0, 0], "```\n{0}myrole không cần thêm cú pháp\n\nCho bạn biết vai mình trong tin nhắn riêng.```")
async def cmd_myrole(message, parameters):
    await _send_role_info(message.author.id)

@cmd('stats', [0, 0], "```\n{0}stats không cần thêm cú pháp\n\nXem trạng thái game.```")
async def cmd_stats(message, parameters):
    if session[0]:
        reply_msg = "Bây giờ là **" + ("day" if session[2] else "night") + "time**. Đang sử dụng **{}** gamemode.".format(
            'roles' if session[6].startswith('roles') else session[6])
        reply_msg += "\n**" + str(len(session[1])) + "** Người chơi đang chơi: **" + str(len([x for x in session[1] if session[1][x][0]])) + "** còn sống, "
        reply_msg += "**" + str(len([x for x in session[1] if not session[1][x][0]])) + "** đã chết\n"
        reply_msg += "```basic\nCòn sống:\n" + "\n".join(get_name(x) + ' (' + x + ')' for x in sort_players(session[1]) if session[1][x][0]) + '\n'
        reply_msg += "Đã chết:\n" + "\n".join(get_name(x) + ' (' + x + ')' for x in sort_players(session[1]) if not session[1][x][0]) + '\n'

        if session[6] in ('random',):
            reply_msg += '\n!stats ko thể dùng trong {} gamemode.```'.format(session[6])
            await reply(message, reply_msg)
            return
        orig_roles = dict(session[7])
        # make a copy
        role_dict = {}
        traitorvill = 0
        traitor_turned = False
        for other in [session[1][x][4] for x in session[1]]:
            if 'traitor' in other:
                traitor_turned = True
                break
        for role in roles: # Fixes !stats crashing with !frole of roles not in game
            role_dict[role] = [0, 0]
            # [min, max] for traitor and similar roles
        for player in session[1]:
            # Get maximum numbers for all roles
            role_dict[get_role(player, 'role')][0] += 1
            role_dict[get_role(player, 'role')][1] += 1
            if get_role(player, 'role') in ['villager', 'traitor']:
                traitorvill += 1

        #reply_msg += "Total roles: " + ", ".join(sorted([x + ": " + str(roles[x][3][len(session[1]) - MIN_PLAYERS]) for x in roles if roles[x][3][len(session[1]) - MIN_PLAYERS] > 0])).rstrip(", ") + '\n'
        # ^ saved this beast for posterity

        reply_msg += "Roles tổng cộng: "
        total_roles = dict(orig_roles)
        reply_msg += ', '.join("{}: {}".format(x, total_roles[x]) for x in sort_roles(total_roles))

        for role in list(role_dict):
            # list is used to make a copy
            if role in TEMPLATES_ORDERED:
                del role_dict[role]

        if traitor_turned:
            role_dict['wolf'][0] += role_dict['traitor'][0]
            role_dict['wolf'][1] += role_dict['traitor'][1]
            role_dict['traitor'] = [0, 0]

        for player in session[1]:
            # Subtract dead players
            if not session[1][player][0]:
                role = get_role(player, 'role')
                reveal = get_role(player, 'deathstats')

                if role == 'traitor' and traitor_turned:
                    # player died as traitor but traitor turn message played, so subtract from wolves
                    reveal = 'wolf'

                if reveal == 'villager':
                    traitorvill -= 1
                    # could be traitor or villager
                    if 'traitor' in role_dict:
                        role_dict['traitor'][0] = max(0, role_dict['traitor'][0] - 1)
                        if role_dict['traitor'][1] > traitorvill:
                            role_dict['traitor'][1] = traitorvill

                    role_dict['villager'][0] = max(0, role_dict['villager'][0] - 1)
                    if role_dict['villager'][1] > traitorvill:
                        role_dict['villager'][1] = traitorvill
                else:
                    # player died is definitely that role
                    role_dict[reveal][0] = max(0, role_dict[reveal][0] - 1)
                    role_dict[reveal][1] = max(0, role_dict[reveal][1] - 1)

        reply_msg += "\nRoles hiện tại: "
        for template in TEMPLATES_ORDERED:
            if template in orig_roles:
                del orig_roles[template]
        for role in sort_roles(orig_roles):
            if role_dict[role][0] == role_dict[role][1]:
                if role_dict[role][0] == 1:
                    reply_msg += "éo bik"
                else:
                    reply_msg += "éo bik"
                reply_msg += ": "
            else:
                reply_msg += ": {}-{}"
            reply_msg += ", "
        reply_msg = reply_msg.rstrip(", ") + "```"
        await reply(message, reply_msg)
    else:
        players = ["{} ({})".format(get_name(x), x) for x in sort_players(session[1])]
        num_players = len(session[1])
        if num_players == 0:
            await client.send_message(message.channel, "Chưa có game nào đang diễn ra. Thử xài {}join để bắt đầu 1 game mới!".format(BOT_PREFIX))
        else:
            await client.send_message(message.channel, "{} người chơi trong sảnh: ```\n{}\n```".format(num_players, '\n'.join(players)))

@cmd('revealroles', [1, 1], "```\n{0}revealroles takes no arguments\n\nDisplays what each user's roles are and sends it in pm.```", 'rr')
async def cmd_revealroles(message, parameters):
    msg = "**Gamemode**: {}```diff\n".format(session[6])
    for player in sort_players(session[1]):
        msg += "{} ".format('+' if session[1][player][0] else '-') + get_name(player) + ' (' + player + '): ' + get_role(player, 'actual')
        msg += "; action: " + session[1][player][2] + "; other: " + ' '.join(session[1][player][4]) + "\n"
    msg += "```"
    await client.send_message(message.channel, msg)
    await log(2, "{0} ({1}) REVEALROLES".format(message.author.name, message.author.id))

@cmd('see', [2, 0], "```\n{0}see <player>\n\nNếu là tiên tri, dùng lệnh để xem vai của <player>.```")
async def cmd_see(message, parameters):
    if not session[0] or message.author.id not in session[1] or not session[1][message.author.id][0]:
        return
    if not get_role(message.author.id, 'role') in COMMANDS_FOR_ROLE['see']:
        return
    if session[2]:
        await reply(message, "Chỉ có thể soi vào ban đêm.")
        return
    if session[1][message.author.id][2]:
        await reply(message, "Bạn đã dùng năng lực rồi.")
    else:
        if parameters == "":
            await reply(message, roles[session[1][message.author.id][1]][2])
        else:
            player = get_player(parameters)
            if player:
                if player == message.author.id:
                    await reply(message, "Mi tự biết mi là ai rồi ha :>.")
                elif player in [x for x in session[1] if not session[1][x][0]]:
                    await reply(message, "Người chơi **" + get_name(player) + "** chết rồi!")
                else:
                    session[1][message.author.id][2] = player
                    seen_role = get_role(player, 'seen')
                    if (session[1][player][4].count('deceit_totem2') +\
                    session[1][message.author.id][4].count('deceit_totem2')) % 2 == 1:
                        if seen_role == 'wolf':
                            seen_role = 'villager'
                        else:
                            seen_role = 'wolf'
                    await reply(message, "Bạn thấy 1 điềm báo... trong điềm báo bạn thấy **" + get_name(player) + "** là một **" + seen_role + "**!")
                    await log(1, "{0} ({1}) SEE {2} ({3}) AS {4}".format(get_name(message.author.id), message.author.id, get_name(player), player, seen_role))
            else:
                await reply(message, "Không tìm thấy " + parameters)

@cmd('kill', [2, 0], "```\n{0}kill <player>\n\nNếu là sói, bầu chọn giết <player>. Nếu là "
                     "thợ săn, <player> sẽ chết tối hôm sau.```")
async def cmd_kill(message, parameters):
    if not session[0] or message.author.id not in session[1] or get_role(message.author.id, 'role') not in COMMANDS_FOR_ROLE['kill'] or not session[1][message.author.id][0]:
        return
    if session[2]:
        await reply(message, "Chỉ có thể giết vào ban đêm.")
        return
    if parameters == "":
        await reply(message, roles[session[1][message.author.id][1]][2])
    else:
        if get_role(message.author.id, 'role') == 'hunter':
            if 'hunterbullet' not in session[1][message.author.id][4]:
                await reply(message, "Bạn đã giết 1 người trong game này rồi.")
                return
            elif session[1][message.author.id][2] not in ['', message.author.id]:
                await reply(message, "Bạn đã chọn giết **{}** rồi.".format(get_name(session[1][message.author.id][2])))
                return
        player = get_player(parameters)
        if player:
            if player == message.author.id:
                await reply(message, "Tau éo cho mầy tự tử đâu.")
            elif roles[get_role(message.author.id, 'role')][0] == 'wolf' and player in \
            [x for x in session[1] if roles[get_role(x, 'role')][0] == 'wolf' and get_role(x, 'role') != 'cultist']:
                await reply(message, "Rảnh háng quá đi bóp dái đồng đội à?.")
            elif player in [x for x in session[1] if not session[1][x][0]]:
                await reply(message, "Người chơi **" + get_name(player) + "** chết rồi!")
            else:
                session[1][message.author.id][2] = player
                if roles[get_role(message.author.id, 'role')][0] == 'wolf':
                    await reply(message, "Đã chọn giết **" + get_name(player) + "**.")
                    await wolfchat("**{}** đã bầu giết **{}**.".format(get_name(message.author.id), get_name(player)))
                elif get_role(message.author.id, 'role') == 'hunter':
                    await reply(message, "Bạn đã chọn giết **" + get_name(player) + "**.")
                await log(1, "{0} ({1}) KILL {2} ({3})".format(get_name(message.author.id), message.author.id, get_name(player), player))
        else:        
            await reply(message, "Không tìm thấy người chơi " + parameters)

@cmd('vote', [0, 0], "```\n{0}vote [<gamemode | player>]\n\nVotes for <gamemode> during the join phase or votes to lynch <player> during the day. If no arguments "
                     "are given, replies with a list of current votes.```", 'v')
async def cmd_vote(message, parameters):
    if session[0]:
        await cmd_lynch(message, parameters)
    else:
        if message.channel.is_private:
            await reply(message, "Hãy vote ở phòng chơi.")
            return
        if parameters == "":
            await cmd_votes(message, parameters)
        else:
            if session[6]:
                await reply(message, "Một Admin đã set chế độ chơi rồi.")
                return
            if message.author.id in session[1]:
                choice, num = _autocomplete(parameters, gamemodes)
                if num == 0:
                    await reply(message, "Không tìm thấy {}".format(parameters))
                elif num == 1:
                    session[1][message.author.id][2] = choice
                    await reply(message, "bạn đã chọn chế độ chơi **{}**.".format(choice))
                else:
                    await reply(message, "Multiple options: {}".format(', '.join(sorted(choice))))
            else:
                await reply(message, "Bạn không thể bầu nếu bạn không chơi!")
        
@cmd('lynch', [0, 0], "```\n{0}lynch [<player>]\n\nbầu treo cổ [<player>] vào ban ngày. Nếu không có ai được nêu, sẽ cho danh sách votes.```")
async def cmd_lynch(message, parameters):
    if not session[0] or not session[2]:
        return
    if parameters == "":
        await cmd_votes(message, parameters)
    else:
        if message.author.id not in session[1]:
            return
        if message.channel.is_private:
            await reply(message, "Hãy xài lệnh treo cổ ở phòng chơi.")
            return
        if 'injured' in session[1][message.author.id][4]:
            await reply(message, "Bạn đang chấn thương và không vote được.")
            return
        to_lynch = get_player(parameters.split(' ')[0])
        if not to_lynch:
            to_lynch = get_player(parameters)
        if to_lynch:
            if to_lynch in [x for x in session[1] if not session[1][x][0]]:
                await reply(message, "Người chơi **" + get_name(to_lynch) + "** chết rồi!")
            else:
                session[1][message.author.id][2] = to_lynch
                await reply(message, "Bạn đã bầu chọn treo cổ **" + get_name(to_lynch) + "**.")
                await log(1, "{0} ({1}) LYNCH {2} ({3})".format(get_name(message.author.id), message.author.id, get_name(to_lynch), to_lynch))
        else:
            await reply(message, "Không tìm thấy người chơi " + parameters)

@cmd('votes', [0, 0], "```\n{0}votes không cần thêm cú pháp\n\nHiện thị gamemode đang bầu hoặc trạng thái vote treo cổ của ngày hôm nay.```")
async def cmd_votes(message, parameters):
    if not session[0]:
        vote_dict = {'start' : []}
        for player in session[1]:
            if session[1][player][2] in vote_dict:
                vote_dict[session[1][player][2]].append(player)
            elif session[1][player][2] != '':
                vote_dict[session[1][player][2]] = [player]
            if session[1][player][1] == 'start':
                vote_dict['start'].append(player)
        reply_msg = "**{}** người chơi{} ở trong sảnh, **{}** phiếu bầu{} cần thiết để chọn chế độ chơi, **{}** phiếu bầu cần để bắt đầu game.```\n".format(
            len(session[1]), '' if len(session[1]) == 1 else 's', len(session[1]) // 2 + 1, '' if len(session[1]) // 2 + 1 == 1 else 's',
            max(2, min(len(session[1]) // 4 + 1, 4)))
        for gamemode in vote_dict:
            if gamemode == 'start':
                continue
            reply_msg += "{} ({} vote{}): {}\n".format(gamemode, len(vote_dict[gamemode]), '' if len(vote_dict[gamemode]) == 1 else 's',
                                                     ', '.join(map(get_name, vote_dict[gamemode])))
        reply_msg += "{} vote{} để bắt đầu: {}\n```".format(len(vote_dict['start']), '' if len(vote_dict['start']) == 1 else 's',
                                                       ', '.join(map(get_name, vote_dict['start'])))
        await reply(message, reply_msg)
    elif session[0] and session[2]:
        vote_dict = {'abstain': []}
        alive_players = [x for x in session[1] if session[1][x][0]]
        able_voters = [x for x in alive_players if 'injured' not in session[1][x][4]]
        for player in able_voters:
            if session[1][player][2] in vote_dict:
                vote_dict[session[1][player][2]].append(player)
            elif session[1][player][2] != '':
                vote_dict[session[1][player][2]] = [player]
        abstainers = vote_dict['abstain']
        reply_msg = "**{}** người chơi còn sống, **{}** phiếu bầu để treo cổ, **{}** người chơi có thể bầu, **{}** người chơi{} bỏ phiếu trắng.\n".format(
            len(alive_players), len(able_voters) // 2 + 1, len(able_voters), len(abstainers), '' if len(abstainers) == 1 else 's')

        if len(vote_dict) == 1 and vote_dict['abstain'] == []:
            reply_msg += "Chưa ai đưa phiếu bầu cả. Xài `{}lynch <player>` trong chat để treo cổ <player>. ".format(BOT_PREFIX, client.get_channel(GAME_CHANNEL).name)
        else:
            reply_msg += "Đang vote: ```\n"
            for voted in [x for x in vote_dict if x != 'abstain']:
                reply_msg += "{} ({}) ({} vote{}): {}\n".format(
                    get_name(voted), voted, len(vote_dict[voted]), '' if len(vote_dict[voted]) == 1 else 's', ', '.join(['{} ({})'.format(get_name(x), x) for x in vote_dict[voted]]))
            reply_msg += "{} vote{} phiếu trắng: {}\n".format(
                len(vote_dict['abstain']), '' if len(vote_dict['abstain']) == 1 else 's', ', '.join(['{} ({})'.format(get_name(x), x) for x in vote_dict['abstain']]))            
            reply_msg += "```"
        await reply(message, reply_msg)

@cmd('retract', [0, 0], "```\n{0}retract không cần thêm cú pháp\n\nRút lại phiếu bầu hoặc quyết định của bạn "
                        "khi là vai đặc biệt.```", 'r')
async def cmd_retract(message, parameters):
    if message.author.id not in session[1]:
        # not playing
        return
    if not session[0] and session[1][message.author.id][2] == '' and session[1][message.author.id][1] == '':
        # no vote to start nor vote for gamemode
        return
    if session[0] and session[1][message.author.id][2] == '':
        # no target
        return
    if not session[0]:
        if message.channel.is_private:
            await reply(message, "Hãy xài lệnh ở game channel.")
            return
        session[1][message.author.id][2] = ''
        session[1][message.author.id][1] = ''
        await reply(message, "Bạn đã rút lại phiếu bầu.")
    elif session[0] and session[1][message.author.id][0]:
        if session[2]:
            if message.channel.is_private:
                await reply(message, "Hãy xài lệnh retract trong game channel.")
                return
            session[1][message.author.id][2] = ''
            await reply(message, "Bạn đã rút lại phiếu bầu.")
            await log(1, "{0} ({1}) RETRACT VOTE".format(get_name(message.author.id), message.author.id))
        else:
            if session[1][message.author.id][1] in ACTUAL_WOLVES:
                if not message.channel.is_private:
                    try:
                        await client.send_message(message.author, "Xài lệnh retract trong chat riêng với bot.")
                    except:
                        pass
                    return
                session[1][message.author.id][2] = ''
                await reply(message, "Bạn đã rút lại quyết định.")
                await wolfchat("**{}** đã rút lại quyết định giết.".format(get_name(message.author.id)))
                await log(1, "{0} ({1}) RETRACT KILL".format(get_name(message.author.id), message.author.id))

@cmd('abstain', [0, 2], "```\n{0}abstain không cần thêm cú pháp\n\nBỏ phiếu trắng cho hôm nay.```", 'abs', 'nl')
async def cmd_abstain(message, parameters):
    if not session[0] or not session[2] or not message.author.id in [x for x in session[1] if session[1][x][0]]:
        return
    if session[4][1] == timedelta(0):
        await client.send_message(client.get_channel(GAME_CHANNEL), "Dân làng không thể bỏ phiếu trắng vào ngày đầu tiên. :joy:")
        return
    session[1][message.author.id][2] = 'abstain'
    await log(1, "{0} ({1}) ABSTAIN".format(get_name(message.author.id), message.author.id))
    await client.send_message(client.get_channel(GAME_CHANNEL), "**{}** đã chọn không treo ai hôm nay.".format(get_name(message.author.id)))

@cmd('coin', [0, 0], "```\n{0}coin takes no arguments\n\nFlips a coin. Don't use this for decision-making, especially not for life or death situations.```")
async def cmd_coin(message, parameters):
    value = random.randint(1,100)
    reply_msg = ''
    if value == 1:
        reply_msg = 'its side'
    elif value == 100:
        reply_msg = client.user.name
    elif value < 50:
        reply_msg = 'heads'
    else:
        reply_msg = 'tails'
    await reply(message, 'The coin landed on **' + reply_msg + '**!')

@cmd('admins', [0, 0], "```\n{0}admins Không cần thêm cú pháp\n\nĐưa danh sách admin đang online nếu xài trong chat riêng với bot, và **báo động** cho các admin nếu xài trong game channel (**USE ONLY WHEN NEEDED**).```")
async def cmd_admins(message, parameters):
    await reply(message, 'Admin đang online: ' + ', '.join(['<@{}>'.format(x) for x in ADMINS if is_online(x)]))

@cmd('fday', [1, 2], "```\n{0}fday takes no arguments\n\nForces night to end.```")
async def cmd_fday(message, parameters):
    if session[0] and not session[2]:
        session[2] = True
        await reply(message, ":thumbsup:")
        await log(2, "{0} ({1}) FDAY".format(message.author.name, message.author.id))

@cmd('fnight', [1, 2], "```\n{0}fnight takes no arguments\n\nForces day to end.```")
async def cmd_fnight(message, parameters):
    if session[0] and session[2]:
        session[2] = False
        await reply(message, ":thumbsup:")
        await log(2, "{0} ({1}) FNIGHT".format(message.author.name, message.author.id))

@cmd('frole', [1, 2], "```\n{0}frole <player> <role>\n\nSets <player>'s role to <role>.```")
async def cmd_frole(message, parameters):
    if parameters == '':
        return
    player = parameters.split(' ')[0]
    role = parameters.split(' ', 1)[1]
    temp_player = get_player(player)
    if temp_player:
        if session[0]:
            if role in roles or role in ['cursed']:
                if role not in ['cursed'] + TEMPLATES_ORDERED:
                    session[1][temp_player][1] = role
                if role == 'cursed villager':
                    session[1][temp_player][1] = 'villager'
                    for i in range(session[1][temp_player][3].count('cursed')):
                        session[1][temp_player][3].remove('cursed')
                    session[1][temp_player][3].append('cursed')
                elif role == 'cursed':
                    for i in range(session[1][temp_player][3].count('cursed')):
                        session[1][temp_player][3].remove('cursed')
                    session[1][temp_player][3].append('cursed')
                elif role in TEMPLATES_ORDERED:
                    for i in range(session[1][temp_player][3].count(role)):
                        session[1][temp_player][3].remove(role)
                    session[1][temp_player][3].append(role)
                await reply(message, "Successfully set **{}**'s role to **{}**.".format(get_name(temp_player), role))
            else:
                await reply(message, "Cannot find role named **" + role + "**")
        else:
            session[1][temp_player][1] = role
    else:
        await reply(message, "Cannot find player named **" + player + "**")
    await log(2, "{0} ({1}) FROLE {2}".format(message.author.name, message.author.id, parameters))

@cmd('force', [1, 2], "```\n{0}force <player> <target>\n\nSets <player>'s target flag (session[1][player][2]) to <target>.```")
async def cmd_force(message, parameters):
    if parameters == '':
        await reply(message, commands['force'][2].format(BOT_PREFIX))
        return
    player = parameters.split(' ')[0]
    target = ' '.join(parameters.split(' ')[1:])
    temp_player = get_player(player)
    if temp_player:
        session[1][temp_player][2] = target
        await reply(message, "Successfully set **{}**'s target to **{}**.".format(get_name(temp_player), target))
    else:
        await reply(message, "Cannot find player named **" + player + "**")
    await log(2, "{0} ({1}) FORCE {2}".format(message.author.name, message.author.id, parameters))

@cmd('session', [1, 1], "```\n{0}session takes no arguments\n\nReplies with the contents of the session variable in pm for debugging purposes. Admin only.```")
async def cmd_session(message, parameters):
    await client.send_message(message.author, "```py\n{}\n```".format(str(session)))
    await log(2, "{0} ({1}) SESSION".format(message.author.name, message.author.id))

@cmd('time', [0, 0], "```\n{0}time không cần thêm cú pháp\n\nXem thời gian trong game.```", 't')
async def cmd_time(message, parameters):
    if session[0]:
        seconds = 0
        timeofday = ''
        sunstate = ''
        if session[2]:
            seconds = DAY_TIMEOUT - (datetime.now() - session[3][1]).seconds
            timeofday = 'buổi sáng'
            sunstate = 'hoàng hôn'
        else:
            seconds = NIGHT_TIMEOUT - (datetime.now() - session[3][0]).seconds
            timeofday = 'buổi tối'
            sunstate = 'bình minh'
        await reply(message, "Bây giờ là **{0}**. Có **{1:02d}:{2:02d}** tới khi {3}.".format(timeofday, seconds // 60, seconds % 60, sunstate))
    else:
        if len(session[1]) > 0:
            timeleft = GAME_START_TIMEOUT - (datetime.now() - session[5]).seconds
            await reply(message, "Còn **{0:02d}:{1:02d}** tới khi game tự hủy. :cry:"
                                 "GAME_START_TIMEOUT is currently set to **{2:02d}:{3:02d}**.".format(
                                     timeleft // 60, timeleft % 60, GAME_START_TIMEOUT // 60, GAME_START_TIMEOUT % 60))              

@cmd('give', [2, 0], "```\n{0}give <player>\n\nNếu là thầy bùa, đưa bùa cho <player>. Bạn có thể xem bùa mình đang giữ bằng lệnh `myrole` trong chat riêng với bot.```")
async def cmd_give(message, parameters):
    if not session[0] or message.author.id not in session[1] or session[1][message.author.id][1] not in ['shaman', 'crazed shaman'] or not session[1][message.author.id][0]:
        return
    if session[2]:
        await reply(message, "Bạn chỉ có thể đưa bùa chú vào ban đêm.")
        return
    if session[1][message.author.id][2] not in totems:
        await reply(message, "Bạn đã đưa bùa chú cho ** rồi!" + get_name(session[1][message.author.id][2]) + "**.")
    else:
        if parameters == "":
            await reply(message, roles[session[1][message.author.id][1]][2])
        else:
            player = get_player(parameters)
            if player:
                if player in [x for x in session[1] if not session[1][x][0]]:
                    await reply(message, "Người chơi **" + get_name(player) + "** chết rồi!")
                else:
                    totem = session[1][message.author.id][2]
                    session[1][player][4].append(totem)
                    session[1][message.author.id][2] = player
                    await reply(message, "Bạn đã đưa bùa cho ** :smiling_imp:" + get_name(player) + "**.")
                    await log(1, "{0} ({1}) GAVE {2} ({3}) {4}".format(get_name(message.author.id), message.author.id, get_name(player), player, totem))
            else:        
                await reply(message, "Không tìm thấy người chơi " + parameters)

@cmd('info', [0, 0], "```\n{0}info không cần thêm cú pháp\n\nCho thông tin cách hoạt động của game.```")
async def cmd_info(message, parameters):
    msg = "Trong trò chơi, có 2 phe, dân làng và ma sói. Dân làng cố gắng giết hết sói, ngược lại sói cố gắng ăn hết dân làng.\n"
    msg += "Có 2 giai đoạn, đêm và ngày. Vào ban đêm, Phe sói chọn 1 nạn nhân để giết, Và các dân làng có chức năng đặc biệt như tiên tri hoạt động. "
    msg += "Vào ban ngày, Dân làng bàn loạn với nhau và chọn người để treo cổ. "
    msg += "Khi bạn đã chết, Bạn không thể chat ở channel game nhưng có thể chat ở các channel Musik, Off-topic và Spectate.\n\n"
    msg += "Để tham gia game, dùng lệnh `{0}join`. Nếu bạn không chat được ở channel game, thì bạn đã chết hoặc có 1 game đang diễn ra.\n"
    msg += "Để xem danh sách các vai, xài lệnh `{0}roles`. Để biết chi tiết của 1 vai, xài `{0}role <vai>`. Để xem diễn biến của game, xài `{0}stats`. "
    msg += "Để xem danh sách các lệnh, xài `{0}list`. Để có chi tiết về mỗi lệnh, xài `{0}help <lệnh>`. Để xem thời gian trong game, xài `{0}time`.\n\n"
    msg += "Hãy cho Lucifer biết các lỗi mà các bạn gặp phải."
    await reply(message, msg.format(BOT_PREFIX))

@cmd('notify_role', [0, 0], "```\n{0}notify_role [<true|false>]\n\nGives or take the " + WEREWOLF_NOTIFY_ROLE_NAME + " role.```")
async def cmd_notify_role(message, parameters):
    if not WEREWOLF_NOTIFY_ROLE:
        await reply(message, "Error: A " + WEREWOLF_NOTIFY_ROLE_NAME + " Vai không tồn tại, hãy cho Lucifer biết.")
        return
    member = client.get_server(WEREWOLF_SERVER).get_member(message.author.id)
    if not member:
        await reply(message, "You are not in the server!")
    has_role = (WEREWOLF_NOTIFY_ROLE in member.roles)
    if parameters == '':
        has_role = not has_role
    elif parameters in ['true', '+', 'yes']:
        has_role = True
    elif parameters in ['false', '-', 'no']:
        has_role = False
    else:
        await reply(message, commands['notify_role'][2].format(BOT_PREFIX))
        return
    if has_role:
        await client.add_roles(member, WEREWOLF_NOTIFY_ROLE)
        await reply(message, "You will be notified by @" + WEREWOLF_NOTIFY_ROLE.name + ".")
    else:
        await client.remove_roles(member, WEREWOLF_NOTIFY_ROLE)
        await reply(message, "You will not be notified by @" + WEREWOLF_NOTIFY_ROLE.name + ".")

@cmd('ignore', [1, 1], "```\n{0}ignore <add|remove|list> <user>\n\nAdds or removes <user> from the ignore list, or outputs the ignore list.```")
async def cmd_ignore(message, parameters):
    parameters = ' '.join(message.content.strip().split(' ')[1:])
    parameters = parameters.strip()
    global IGNORE_LIST
    if parameters == '':
        await reply(message, commands['ignore'][2].format(BOT_PREFIX))
    else:
        action = parameters.split(' ')[0].lower()
        target = ' '.join(parameters.split(' ')[1:])
        member_by_id = client.get_server(WEREWOLF_SERVER).get_member(target.strip('<@!>'))
        member_by_name = client.get_server(WEREWOLF_SERVER).get_member_named(target)
        member = None
        if member_by_id:
            member = member_by_id
        elif member_by_name:
            member = member_by_name
        if action not in ['+', 'add', '-', 'remove', 'list']:
            await reply(message, "Error: invalid flag `" + action + "`. Supported flags are add, remove, list")
            return
        if not member and action != 'list':
            await reply(message, "Error: could not find target " + target)
            return
        if action in ['+', 'add']:
            if member.id in IGNORE_LIST:
                await reply(message, member.name + " is already in the ignore list!")
            else:
                IGNORE_LIST.append(member.id)
                await reply(message, member.name + " was added to the ignore list.")
        elif action in ['-', 'remove']:
            if member.id in IGNORE_LIST:
                IGNORE_LIST.remove(member.id)
                await reply(message, member.name + " was removed from the ignore list.")
            else:
                await reply(message, member.name + " is not in the ignore list!")
        elif action == 'list':
            if len(IGNORE_LIST) == 0:
                await reply(message, "The ignore list is empty.")
            else:
                msg_dict = {}
                for ignored in IGNORE_LIST:
                    member = client.get_server(WEREWOLF_SERVER).get_member(ignored)
                    msg_dict[ignored] = member.name if member else "<user not in server with id " + ignored + ">"
                await reply(message, str(len(IGNORE_LIST)) + " ignored users:\n```\n" + '\n'.join([x + " (" + msg_dict[x] + ")" for x in msg_dict]) + "```")
        else:
            await reply(message, commands['ignore'][2].format(BOT_PREFIX))
        await log(2, "{0} ({1}) IGNORE {2}".format(message.author.name, message.author.id, parameters))

# TODO
async def cmd_pingif(message, parameters):
    global pingif_dict
    if parameters == '':
        if message.author.id in pingif_dict:
            await reply(message, "You will be notified when there are at least **{}** players.".format(pingif_dict[message.author.id]))
        else:
            await reply(message, "You have not set a pingif yet. `{}pingif <number of players>`".format(BOT_PREFIX))
    elif parameters.isdigit():
        num = int(parameters)
        if num in range(MIN_PLAYERS, MAX_PLAYERS + 1):
            pingif_dict[message.author.id] = num
            await reply(message, "You will be notified when there are at least **{}** players.".format(pingif_dict[message.author.id]))
        else:
            await reply(message, "Please enter a number between {} and {} players.".format(MIN_PLAYERS, MAX_PLAYERS))
    else:
        await reply(message, "Please enter a valid number of players to be notified at.")

@cmd('online', [1, 1], "```\n{0}online takes no arguments\n\nNotifies all online users.```")
async def cmd_online(message, parameters):
    members = [x.id for x in message.server.members]
    online = ["<@{}>".format(x) for x in members if is_online(x)]
    await reply(message, "PING! {}".format(''.join(online)))

@cmd('notify', [0, 0], "```\n{0}notify [<true|false>]\n\nNotifies all online users who want to be notified, or adds/removes you from the notify list.```")
async def cmd_notify(message, parameters):
    if session[0]:
        return
    notify = message.author.id in notify_me
    if parameters == '':
        online = ["<@{}>".format(x) for x in notify_me if is_online(x) and x not in session[1]]
        await reply(message, "PING! {}".format(''.join(online)))
    elif parameters in ['true', '+', 'yes']:
        if notify:
            await reply(message, "Bạn đã ở trong danh sách sẽ được thông báo rồi.")
            return
        notify_me.append(message.author.id)
        await reply(message, "Bạn sẽ được thông báo khi có game bởi {}notify.".format(BOT_PREFIX))
    elif parameters in ['false', '-', 'no']:
        if not notify:
            await reply(message, "Bạn không nằm trong danh sách được thông báo.")
            return
        notify_me.remove(message.author.id)
        await reply(message, "Bạn sẽ không được thông báo bởi {}notify.".format(BOT_PREFIX))
    else:
        await reply(message, commands['notify'][2].format(BOT_PREFIX))        

@cmd('getrole', [1, 1], "```\n{0}getrole <player> <revealtype>\n\nTests get_role command.```")
async def cmd_getrole(message, parameters):
    if not session[0] or parameters == '':
        await reply(message, commands['getrole'][2].format(BOT_PREFIX))
        return
    player = parameters.split(' ')[0]
    revealtype = ' '.join(parameters.split(' ')[1:])
    temp_player = get_player(player)
    if temp_player:
        role = get_role(temp_player, revealtype)
        await reply(message, "**{}** is a **{}** using revealtype **{}**".format(get_name(temp_player), role, revealtype))
    else:
        await reply(message, "Cannot find player named **" + player + "**")

@cmd('visit', [2, 0], "```\n{0}visit <player>\n\nNếu là Harlot, ghé thăm <player>. Bạn có thể ở nhà bằng cách thăm chính mình. "
                      "Bạn sẽ chết nếu thăm 1 con sói hoặc thăm nạn nhân 1 con sói.```")
async def cmd_visit(message, parameters):
    if not session[0] or message.author.id not in session[1] or session[1][message.author.id][1] != 'harlot' or not session[1][message.author.id][0]:
        return
    if session[2]:
        await reply(message, "Chỉ có thể ghé thăm vào ban đêm.")
        return
    if session[1][message.author.id][2]:
        await reply(message, "Bạn đã đang ngủ với **{}** rồi!.:cry:".format(get_name(session[1][message.author.id][2])))
    else:
        if parameters == "":
            await reply(message, roles[session[1][message.author.id][1]][2])
        else:
            player = get_player(parameters)
            if player:
                if player == message.author.id:
                    await reply(message, "Bạn đã chọn ở nhà.")
                    session[1][message.author.id][2] = message.author.id
                    await log(1, "{0} ({1}) STAY HOME".format(get_name(message.author.id), message.author.id))
                elif player in [x for x in session[1] if not session[1][x][0]]:
                    await reply(message, "Player **" + get_name(player) + "** is dead!")
                else:
                    await reply(message, "Bạn đang ngủ cùng **{}**. Nệm ấm chăn êm :>!".format(get_name(player)))
                    session[1][message.author.id][2] = player
                    member = client.get_server(WEREWOLF_SERVER).get_member(player)
                    try:
                        await client.send_message(member, "Bạn đang ngủ cùng Thúy Kiều. Ngủ ngon :>!".format(get_name(message.author.id)))
                    except:
                        pass
                    await log(1, "{0} ({1}) VISIT {2} ({3})".format(get_name(message.author.id), message.author.id, get_name(player), player))
            else:        
                await reply(message, "Không tìm thấy người chơi " + parameters)

@cmd('totem', [0, 0], "```\n{0}totem [<totem>]\n\nCho biết thông tin về 1 lá bùa, hoặc cho danh sách các bùa trong game.```", 'totems')
async def cmd_totem(message, parameters):
    if not parameters == '':
        reply_totems = []
        for totem in totems:
            if totem.startswith(parameters):
                reply_totems.append(totem)
        if _autocomplete(parameters, totems)[1] == 1:
            totem = _autocomplete(parameters, totems)[0]
            reply_msg = "```\n"
            reply_msg += totem[0].upper() + totem[1:].replace('_', ' ') + "\n\n"
            reply_msg += totems[totem] + "```"
            await reply(message, reply_msg)
            return
    await reply(message, "Các bùa đang có: " + ", ".join(sorted([x.replace('_', ' ') for x in totems])))

@cmd('fgame', [1, 2], "```\n{0}fgame [<gamemode>]\n\nForcibly sets or unsets [<gamemode>].```")
async def cmd_fgame(message, parameters):
    if session[0]:
        return
    if parameters == '':
        if session[6] != '':
            session[6] = ''
            await reply(message, "Successfully unset gamemode.")
        else:
            await reply(message, "Gamemode has not been set.")
    else:
        if parameters.startswith('roles'):
            role_string = ' '.join(parameters.split(' ')[1:])
            if role_string == '':
                await reply(message, "`{}fgame roles wolf:1,traitor:1,shaman:2,cursed villager:2,etc.`".format(BOT_PREFIX))
            else:
                session[6] = parameters
                await reply(message, "Successfully set gamemode roles to `{}`".format(role_string))
        else:
            choices, num = _autocomplete(parameters, gamemodes)
            if num == 1:
                session[6] = choices
                await reply(message, "Successfuly set gamemode to **{}**.".format(choices))
            elif num > 1:
                await reply(message, "Multiple choices: {}".format(', '.join(sorted(choices))))
            else:
                await reply(message, "Could not find gamemode {}".format(parameters))
    await log(2, "{0} ({1}) FGAME {2}".format(message.author.name, message.author.id, parameters))

@cmd('ftemplate', [1, 2], "```\n{0}ftemplate <player> [<add|remove|set>] [<template1 [template2 ...]>]\n\nManipulates a player's templates.```")
async def cmd_ftemplate(message, parameters):
    if not session[0]:
        return
    if parameters == '':
        await reply(message, commands['ftemplate'][2].format(BOT_PREFIX))
        return
    params = parameters.split(' ')
    player = get_player(params[0])
    if len(params) > 1:
        action = parameters.split(' ')[1]
    else:
        action = ""
    if len(params) > 2:
        templates = parameters.split(' ')[2:]
    else:
        templates = []
    if player:
        reply_msg = "Successfully "
        if action in ['+', 'add', 'give']:
            session[1][player][3] += templates
            reply_msg += "added templates **{0}** to **{1}**."
        elif action in ['-', 'remove', 'del']:
            for template in templates[:]:
                if template in session[1][player][3]:
                    session[1][player][3].remove(template)
                else:
                    templates.remove(template)
            reply_msg += "removed templates **{0}** from **{1}**."
        elif action in ['=', 'set']:
            session[1][player][3] = templates
            reply_msg += "set **{1}**'s templates to **{0}**."
        else:
            reply_msg = "**{1}**'s templates: " + ', '.join(session[1][player][3])
    else:
        reply_msg = "Could not find player {1}."

    await reply(message, reply_msg.format(', '.join(templates), get_name(player)))
    await log(2, "{0} ({1}) FTEMPLATE {2}".format(message.author.name, message.author.id, parameters))

@cmd('fother', [1, 2], "```\n{0}fother <player> [<add|remove|set>] [<other1 [other2 ...]>]\n\nManipulates a player's other flag (totems, traitor).```")
async def cmd_fother(message, parameters):
    if not session[0]:
        return
    if parameters == '':
        await reply(message, commands['fother'][2].format(BOT_PREFIX))
        return
    params = parameters.split(' ')
    player = get_player(params[0])
    if len(params) > 1:
        action = parameters.split(' ')[1]
    else:
        action = ""
    if len(params) > 2:
        others = parameters.split(' ')[2:]
    else:
        others = []
    if player:
        reply_msg = "Successfully "
        if action in ['+', 'add', 'give']:
            session[1][player][4] += others
            reply_msg += "added **{0}** to **{1}**'s other flag."
        elif action in ['-', 'remove', 'del']:
            for other in others[:]:
                if other in session[1][player][4]:
                    session[1][player][4].remove(other)
                else:
                    others.remove(other)
            reply_msg += "removed **{0}** from **{1}**'s other flag."
        elif action in ['=', 'set']:
            session[1][player][4] = others
            reply_msg += "set **{1}**'s other flag to **{0}**."
        else:
            reply_msg = "**{1}**'s other flag: " + ', '.join(session[1][player][4])
    else:
        reply_msg = "Could not find player {1}."

    await reply(message, reply_msg.format(', '.join(others), get_name(player)))
    await log(2, "{0} ({1}) FOTHER {2}".format(message.author.name, message.author.id, parameters))

@cmd('faftergame', [2, 2], "```\n{0}faftergame <command> [<parameters>]\n\nSchedules <command> to run with [<parameters>] after the next game ends.```")
async def cmd_faftergame(message, parameters):
    if parameters == "":
        await reply(message, commands['faftergame'][2].format(BOT_PREFIX))
        return
    command = parameters.split(' ')[0]
    if command in commands:
        global faftergame
        faftergame = message
        await reply(message, "Command `{}` will run after the next game ends.".format(parameters))
    else:
        await reply(message, "{} is not a valid command!".format(command))

@cmd('uptime', [0, 0], "```\n{0}uptime takes no arguments\n\nChecks the bot's uptime.```")
async def cmd_uptime(message, parameters):
    delta = datetime.now() - starttime
    output = [[delta.days, 'day'],
              [delta.seconds // 3600, 'hour'],
              [delta.seconds // 60 % 60, 'minute'],
              [delta.seconds % 60, 'second']]
    for i in range(len(output)):
        if output[i][0] != 1:
            output[i][1] += 's'
    reply_msg = ''
    if output[0][0] != 0:
        reply_msg += "{} {} ".format(output[0][0], output[0][1])
    for i in range(1, len(output)):
        reply_msg += "{} {} ".format(output[i][0], output[i][1])
    reply_msg = reply_msg[:-1]
    await reply(message, "Uptime: **{}**".format(reply_msg))

@cmd('fstasis', [1, 1], "```\n{0}fstasis <player> [<add|remove|set>] [<amount>]\n\nManipulates a player's stasis.```")
async def cmd_fstasis(message, parameters):
    if parameters == '':
        await reply(message, commands['fstasis'][2].format(BOT_PREFIX))
        return
    params = parameters.split(' ')
    player = params[0].strip('<!@>')
    member = client.get_server(WEREWOLF_SERVER).get_member(player)
    name = "user not in server with id " + player
    if member:
        name = member.display_name
    if len(params) > 1:
        action = parameters.split(' ')[1]
    else:
        action = ''
    if len(params) > 2:
        amount = parameters.split(' ')[2]
        if amount.isdigit():
            amount = int(amount)
        else:
            amount = -1
    else:
        amount = -2
    if player.isdigit():
        if action and amount >= -1:
            if amount >= 0:
                if player not in stasis:
                    stasis[player] = 0
                reply_msg = "Successfully "
                if action in ['+', 'add', 'give']:
                    stasis[player] += amount
                    reply_msg += "increased **{0}** ({1})'s stasis by **{2}**."
                elif action in ['-', 'remove', 'del']:
                    amount = min(amount, stasis[player])
                    stasis[player] -= amount
                    reply_msg += "decreased **{0}** ({1})'s stasis by **{2}**."
                elif action in ['=', 'set']:
                    stasis[player] = amount
                    reply_msg += "set **{0}** ({1})'s stasis to **{2}**."
                else:
                    if player not in stasis:
                        amount = 0
                    else:
                        amount = stasis[player]
                    reply_msg = "**{0}** ({1}) is in stasis for **{2}** game{3}."
            else:
                reply_msg = "Stasis must be a non-negative integer."
        else:
            if player not in stasis:
                amount = 0
            else:
                amount = stasis[player]
            reply_msg = "**{0}** ({1}) is in stasis for **{2}** game{3}."
    else:
        reply_msg = "Invalid mention/id: {0}."

    await reply(message, reply_msg.format(name, player, amount, '' if int(amount) == 1 else 's'))
    await log(2, "{0} ({1}) FSTASIS {2}".format(message.author.name, message.author.id, parameters))    

@cmd('gamemode', [0, 0], "```\n{0}gamemode [<gamemode>]\n\nCho biết thông tin về [<gamemode>] hoặc cho danh sách "
                         "các chế độ chơi.```", 'game', 'gamemodes')
async def cmd_gamemode(message, parameters):
    gamemode, num = _autocomplete(parameters, gamemodes)
    if num == 1 and parameters != '':
        await reply(message, "```\nGamemode: {}\nPlayers: {}\nDescription: {}\n\nXài lệnh "
                             "`!roles {} table` để xem các vai có trong gamemode này.```".format(gamemode,
        str(gamemodes[gamemode]['min_players']) + '-' + str(gamemodes[gamemode]['max_players']),
        gamemodes[gamemode]['description'], gamemode))
    else:
        await reply(message, "Available gamemodes: {}".format(', '.join(sorted(gamemodes))))

@cmd('verifygamemode', [1, 1], "```\n{0}verifygamemode [<gamemode>]\n\nChecks to make sure [<gamemode>] is valid.```", 'verifygamemodes')
async def cmd_verifygamemode(message, parameters):
    if parameters == '':
        await reply(message, "```\n{}\n```".format(verify_gamemodes()))
    elif _autocomplete(parameters, gamemodes)[1] == 1:
        await reply(message, "```\n{}\n```".format(verify_gamemode(_autocomplete(parameters, gamemodes)[0])))
    else:
        await reply(message, "Éo có gamemode: {}".format(parameters))

@cmd('shoot', [0, 2], "```\n{0}shoot <player>\n\nNếu có súng, bắn <player> vào ban ngày, chỉ có thể dùng lệnh này ở khung chat server.```")
async def cmd_shoot(message, parameters):
    if not session[0] or message.author.id not in session[1] or not session[1][message.author.id][0]:
        return
    if 'gunner' not in get_role(message.author.id, 'templates'):
        try:
            await client.send_message(message.author, "Ảo tướng sức mạnh?. :joy:")
        except discord.Forbidden:
            pass
        return
    if not session[2]:
        try:
            await client.send_message(message.author, "Bạn chỉ có thể bắn vào ban ngày.")
        except:
            pass
        finally:
            return
    msg = ''
    pm = False
    ded = None
    if session[1][message.author.id][4].count('bullet') < 1:
        msg = "Chú éo còn đạn."
        pm = True
    else:
        if parameters == "":
            msg = commands['shoot'][2].format(BOT_PREFIX)
            pm = True
        else:
            target = get_player(parameters.split(' ')[0])
            if not target:
                target = get_player(parameters)
            if not target:
                msg = 'Không tìm thấy người chơi {}'.format(parameters)
            elif target == message.author.id:
                msg = "Cầm súng ngược kìa!.:joy:"
            elif not session[1][target][0]:
                msg = "Người chơi **{}** chết rồi!".format(get_name(target))
            else:
                wolf = get_role(message.author.id, 'role') in WOLFCHAT_ROLES
                session[1][message.author.id][4].remove('bullet')
                outcome = ''
				if wolf:
					if get_role(target, 'role') in WOLFCHAT_ROLES:
                        outcome = 'miss'
				else:
                    if get_role(target, 'role') in ACTUAL_WOLVES:
                        if get_role(target, 'role') in ['werekitten']:
                            outcome = random.choice(['suicide'] * GUNNER_SUICIDE + ['miss'] * (GUNNER_MISS + GUNNER_HEADSHOT + GUNNER_INJURE))
                        else:
                            outcome = 'killwolf'
                if outcome == '':
                else:
                    outcome = random.choice(['miss'] * GUNNER_MISS + ['suicide'] * GUNNER_SUICIDE \
                                             + ['killvictim'] * GUNNER_HEADSHOT + ['injure'] * GUNNER_INJURE)
                if outcome in ['injure', 'killvictim', 'killwolf']:
                    msg = "**{}** đã bắn **{}** bằng 1 viên đạn bạc! :scream:\n\n".format(get_name(message.author.id), get_name(target))
                if outcome == 'miss':
                    msg += "**{}** đéo biết cách cầm súng và bắn trượt! :joy:".format(get_name(message.author.id))
                elif outcome == 'killwolf':
                    msg += "**{}** là **{}** đã bị bắt toét óc bởi viên đạn bạc! :joy:".format(get_name(target),
                            get_role(target, 'death'))
                    ded = target
                elif outcome == 'suicide':
                    msg += "Trời đụ! **{}** bảo trì súng éo tốt và súng nổ banh mặt bạn ấy rồi! :joy: ".format(get_name(message.author.id))
                    msg += "Dân làng tiếc thương một **gunner** :cry:.".format(get_role(message.author.id, 'death'))
                    ded = message.author.id
                elif outcome == 'killvictim':
                    msg += "**{}** không phải là sói nhưng đã bị trọng thương. Làng đã giết nhầm! :cry:".format(
                            get_name(target), get_role(target, 'death'))
                    ded = target
                elif outcome == 'injure':
                    msg += "**{}** là một dân đen và đã bị thương :cry:. May thay vết thương nhẹ và đã lành vào sáng hôm sau.:smiley:".format(
                            get_name(target))
                    session[1][target][4].append('injured')
                else:
                    msg += "Cái đéo? (đây là 1 lỗi, hãy báo cho Lucifer)"

                await log(1, "{} ({}) SHOOT {} ({}) WITH OUTCOME {}".format(get_name(message.author.id), message.author.id,
                    get_name(target), target, outcome))

    if pm:
        target = message.author
    else:
        target = client.get_channel(GAME_CHANNEL)
    try:
        await client.send_message(target, msg)
    except discord.Forbidden:
        pass

    if ded:
        session[1][ded][0] = False
        member = client.get_server(WEREWOLF_SERVER).get_member(ded)
        if member:
            await client.remove_roles(member, PLAYERS_ROLE)
        await check_traitor()

@cmd('fsay', [1, 1], "```\n{0}fsay <message>\n\nSends <message> to the lobby channel.```")
async def cmd_fsay(message, parameters):
    if parameters:
        await client.send_message(client.get_channel(GAME_CHANNEL), parameters)
        await log(2, "{} ({}) FSAY {}".format(message.author.name, message.author.id, parameters))
    else:
        await reply(message, commands['fsay'][2].format(BOT_PREFIX))
    
@cmd('observe', [2, 0], "```\n{0}observe <player>\n\nNếu bạn là Werecrow, cho bạn biết rằng <player> có ở trên giường hay không.```"
						"Nếu là pháp sư, cho biết nếu <player> có năng lực đặc biệt hay không VD:(seer, etc.).```")
async def cmd_observe(message, parameters):
    if not session[0] or message.author.id not in session[1] or get_role(message.author.id, 'role') not in COMMANDS_FOR_ROLE['observe'] or not session[1][message.author.id][0]:
        return
    if session[2]:
        await reply(message, "Bạn chỉ có thể quan sát vào buổi tối.")
        return
    if get_role(message.author.id, 'role') == 'werecrow':
        if 'observe' in session[1][message.author.id][4]:
            await reply(message, "You are already observing someone!.")
        else:
            if parameters == "":
                await reply(message, roles[session[1][message.author.id][1]][2])
            else:
                player = get_player(parameters)
                if player:
                    if player == message.author.id:
                        await reply(message, "That would be a waste.")
                    elif player in [x for x in session[1] if roles[get_role(x, 'role')][0] == 'wolf' and get_role(x, 'role') != 'cultist']:
                        await reply(message, "Observing another wolf is a waste of time.")
                    elif not session[1][player][0]:
                        await reply(message, "Player **" + get_name(player) + "** is dead!")
                    else:
                        session[1][message.author.id][4].append('observe')
                        await reply(message, "You transform into a large crow and start your flight to **{0}'s** house. You will "
                                            "return after collecting your observations when day begins.".format(get_name(player)))
                        await wolfchat("**{}** is observing **{}**.".format(get_name(message.author.id), get_name(player)))
                        await log(1, "{0} ({1}) OBSERVE {2} ({3})".format(get_name(message.author.id), message.author.id, get_name(player), player))
                        while not session[2] and win_condition() == None and session[0]:
                            await asyncio.sleep(0.1)
                        if 'observe' in session[1][message.author.id][4]:
                            session[1][message.author.id][4].remove('observe')
                        if get_role(player, 'role') in ['seer', 'harlot', 'hunter']\
                            and session[1][player][2] in set(session[1]) - set(player)\
                            or get_role(player, 'role') in ['shaman', 'crazed shaman']\
                            and session[1][player][2] in session[1]:
                                msg = "not in bed all night"
                        else:
                                msg = "sleeping all night long"
                        try:
                            await client.send_message(message.author, "As the sun rises, you conclude that **{}** was {}, and you fly back to your house.".format(
                                get_name(player), msg))
                        except discord.Forbidden:
                            pass
                else:        
                    await reply(message, "Could not find player " + parameters)
    elif get_role(message.author.id, 'role') == 'sorcerer':
        if session[1][message.author.id][2]:
            await reply(message, "You have already used your power.")
        elif parameters == "":
            await reply(message, roles[session[1][message.author.id][1]][2])
        else:
            player = get_player(parameters)
            if player:
                if player == message.author.id:
                    await reply(message, "Rảnh háng quá.")
                elif player in [x for x in session[1] if roles[get_role(x, 'role')][0] == 'wolf' and get_role(x, 'role') != 'cultist']:
                    await reply(message, "Đi rình 1 con sói là 1 điêu thật rảnh háng.")
                elif player in [x for x in session[1] if not session[1][x][0]]:
                    await reply(message, "Người chơi **" + get_name(player) + "** chết rồi!")
                else:
                    session[1][message.author.id][2] = player
                    target_role = get_role(player, 'role')
                    if target_role in ['seer', 'oracle', 'augur']:
                        debug_msg = target_role
                        msg = "**{}** là một **{}**!".format(get_name(player), get_role(player, 'role'))
				else:
                        debug_msg = "là người bình thường"
                        msg = "**{}** không có khả năng đặc biệt.".format(get_name(player))
                    await wolfchat("**{}** đang theo dõi **{}**.".format(get_name(message.author.id), get_name(player)))
                    await reply(message, "Sau khi thực thi nghi lễ, bạn nhận thấy " + msg)
                    await log(1, "{0} ({1}) OBSERVE {2} ({3}) AS {4}".format(get_name(message.author.id), message.author.id, get_name(player), player, debug_msg))
            else:
                await reply(message, "Không tìm thấy người chơi " + parameters)

@cmd('id', [2, 0], "```\n{0}id <player>\n\nNếu bạn là thám tử, điều tra <player> vào ban ngày.```")
async def cmd_id(message, parameters):
    if not session[0] or message.author.id not in session[1] or get_role(message.author.id, 'role') not in COMMANDS_FOR_ROLE['id'] or not session[1][message.author.id][0]:
        return
    if not session[2]:
        await reply(message, "Bạn chỉ có thể điều tra vào buổi sáng.")
        return
    if 'investigate' in session[1][message.author.id][4]:
        await reply(message, "Bạn đang có 1 cuộc điều tra đang tiến hành rồi.")
    else:
        if parameters == "":
            await reply(message, roles[session[1][message.author.id][1]][2])
        else:
            player = get_player(parameters)
            if player:
                if player == message.author.id:
                    await reply(message, "Rảnh háng quá đi điều tra chính mình -_-.")
                elif not session[1][player][0]:
                    await reply(message, "Người chơi **" + get_name(player) + "** chết rồi!")
                else:
                    session[1][message.author.id][4].append('investigate')
                    await reply(message, "Kết quả của cuộc điều tra đã được đưa về. **{}** chính là **{}**!".format(
                        get_name(player), get_role(player, 'role')))
                    await log(1, "{0} ({1}) INVESTIGATE {2} ({3})".format(get_name(message.author.id), message.author.id, get_name(player), player))
                    if random.random() < DETECTIVE_REVEAL_CHANCE:
                        await wolfchat("Ai đó tình cờ làm rơi 1 số giấy tờ, nó cho biết **{}** chính là thám tử! :scream:".format(get_name(message.author.id)))
                        await log(1, "{0} ({1}) DETECTIVE REVEAL".format(get_name(message.author.id), message.author.id))
                    while session[2] and win_condition() == None and session[0]:
                        await asyncio.sleep(0.1)
                    if 'investigate' in session[1][message.author.id][4]:
                        session[1][message.author.id][4].remove('investigate')
            else:        
                await reply(message, "Không tìm thấy người chơi " + parameters)
        
@cmd('frevive', [1, 2], "```\n{0}frevive <player>\n\nRevives <player>. Xài để gỡ lỗi.```")
async def cmd_frevive(message, parameters):
    if not session[0]:
        return
    if parameters == "":
        await reply(message, commands['frevive'][2].format(BOT_PREFIX))
    else:
        player = get_player(parameters)
        if player:
            if session[1][player][0]:
                await reply(message, "Người chơi **{}** vẫn còn sống!".format(player))
            else:
                session[1][player][0] = True
                await reply(message, ":thumbsup:")
        else:
            await reply(message, "Không tìm thấy người chơi {}".format(parameters))

@cmd('pass', [2, 0], "```\n{0}pass không cần thêm cú pháp\n\nChọn không làm việc hôm nay.```")
async def cmd_pass(message, parameters):
    role = get_role(message.author.id, 'role')
    if not session[0] or message.author.id not in session[1] or role not in COMMANDS_FOR_ROLE['pass'] or not session[1][message.author.id][0]:
        return
    if session[2] and role in ('harlot', 'hunter'):
        await reply(message, "Bạn chỉ có thể xài bỏ qua vào ban đêm.")
        return
    if session[1][message.author.id][2] != '':
        return
    if role == 'harlot':
        session[1][message.author.id][2] = message.author.id
        await reply(message, "Bạn đã chọn ở nhà hôm nay.:zzz:")
    elif role == 'hunter':
        session[1][message.author.id][2] = message.author.id
        await reply(message, "Bạn đã chọn éo giết ai hôm nay.:joy:")
    else:
        await reply(message, "Cái đéo? (đây là 1 lỗi; hãy báo cho Lucifer")
    await log(1, "{0} ({1}) PASS".format(get_name(message.author.id), message.author.id))

######### END COMMANDS #############

def has_privileges(level, message):
    if message.author.id == OWNER_ID:
        return True
    elif level == 1 and message.author.id in ADMINS:
        return True
    elif level == 0:
        return True
    else:
        return False

async def reply(message, text): 
    await client.send_message(message.channel, message.author.mention + ', ' + str(text))

async def parse_command(commandname, message, parameters):
    await log(0, 'Parsing command ' + commandname + ' with parameters `' + parameters + '` from ' + message.author.name + ' (' + message.author.id + ')')
    if commandname in commands:
        pm = 0
        if message.channel.is_private:
            pm = 1
        if has_privileges(commands[commandname][1][pm], message):
            try:
                await commands[commandname][0](message, parameters)
            except Exception:
                traceback.print_exc()
                print(session)
                msg = '```py\n{}\n```\n**session:**```py\n{}\n```'.format(traceback.format_exc(), session)
                await log(3, msg)
                await client.send_message(message.channel, "Có lỗi xảy ra và đã được ghi nhận.")
        elif has_privileges(commands[commandname][1][0], message):
            if session[0] and message.author.id in [x for x in session[1] if session[1][x][0]]:
                if commandname in COMMANDS_FOR_ROLE and (get_role(message.author.id, 'role') in COMMANDS_FOR_ROLE[commandname]\
                or not set(get_role(message.author.id, 'templates')).isdisjoint(set(COMMANDS_FOR_ROLE[commandname]))):
                    await reply(message, "Please use command " + commandname + " in channel.")
        elif has_privileges(commands[commandname][1][1], message):
            if session[0] and message.author.id in [x for x in session[1] if session[1][x][0]]:
                if commandname in COMMANDS_FOR_ROLE and get_role(message.author.id, 'role') in COMMANDS_FOR_ROLE[commandname]:
                    try:
                        await client.send_message(message.author, "Hãy xài lệnh " + commandname + " trong tin nhắn riêng với bot.")
                    except discord.Forbidden:
                        pass
            elif message.author.id in ADMINS:
                await reply(message, "Hãy xài lệnh " + commandname + " trong phần tin nhắn riêng với bot.")
        else:
            await log(2, 'User ' + message.author.name + ' (' + message.author.id + ') tried to use command ' + commandname + ' with parameters `' + parameters + '` without permissions!')

async def log(loglevel, text):
    # loglevels
    # 0 = DEBUG
    # 1 = INFO
    # 2 = WARNING
    # 3 = ERROR
    levelmsg = {0 : '[DEBUG] ',
                1 : '[INFO] ',
                2 : '**[WARNING]** ',
                3 : '**[ERROR]** <@' + OWNER_ID + '> '
                }
    logmsg = levelmsg[loglevel] + str(text)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write("[{}] {}\n".format(datetime.now(), logmsg))
    if loglevel >= MIN_LOG_LEVEL:
        await client.send_message(client.get_channel(DEBUG_CHANNEL), logmsg)

def balance_roles(massive_role_list, default_role='villager', num_players=-1):
    if num_players == -1:
        num_players = len(session[1])
    extra_players = num_players - len(massive_role_list)
    if extra_players > 0:
        massive_role_list += [default_role] * extra_players
        return (massive_role_list, "Không có đủ vai; Đã thêm {} {} vào danh sách vai".format(extra_players, default_role))
    elif extra_players < 0:
        random.shuffle(massive_role_list)
        removed_roles = []
        team_roles = [0, 0, 0]
        for role in massive_role_list:
            if role in WOLF_ROLES_ORDERED:
                team_roles[0] += 1
            elif role in VILLAGE_ROLES_ORDERED:
                team_roles[1] += 1
            elif role in NEUTRAL_ROLES_ORDERED:
                team_roles[2] += 1
        for i in range(-1 * extra_players):
            team_fractions = list(x / len(massive_role_list) for x in team_roles)
            roles_to_remove = set()
            if team_fractions[0] > 0.35:
                roles_to_remove |= set(WOLF_ROLES_ORDERED)
            if team_fractions[1] > 0.7:
                roles_to_remove |= set(VILLAGE_ROLES_ORDERED)
            if team_fractions[2] > 0.15:
                roles_to_remove |= set(NEUTRAL_ROLES_ORDERED)
            if len(roles_to_remove) == 0:
                roles_to_remove = set(roles)
                if team_fractions[0] < 0.25:
                    roles_to_remove -= set(WOLF_ROLES_ORDERED)
                if team_fractions[1] < 0.5:
                    roles_to_remove -= set(VILLAGE_ROLES_ORDERED)
                if team_fractions[2] < 0.05:
                    roles_to_remove -= set(NEUTRAL_ROLES_ORDERED)
                if len(roles_to_remove) == 0:
                    roles_to_remove = set(roles)
            for role in massive_role_list[:]:
                if role in roles_to_remove:
                    massive_role_list.remove(role)
                    removed_roles.append(role)
                    break
        return (massive_role_list, "Có quá nhiều vai!; Đã xóa {} khỏi danh sách vai".format(', '.join(sort_roles(removed_roles))))
    return (massive_role_list, '')

async def assign_roles(gamemode):
    massive_role_list = []
    gamemode_roles = get_roles(gamemode, len(session[1]))

    if not gamemode_roles:
        # Second fallback just in case
        gamemode_roles = get_roles('default', len(session[1]))
        session[6] = 'default'
        
    # Generate list of roles
    
    for role in gamemode_roles:
        if role in roles and role not in TEMPLATES_ORDERED:
            massive_role_list += [role] * gamemode_roles[role]
    
    massive_role_list, debugmessage = balance_roles(massive_role_list)
    if debugmessage != '':
        await log(2, debugmessage)
    
    if session[6].startswith('roles'):
        session[7] = dict((x, massive_role_list.count(x)) for x in roles if x in massive_role_list)
    else:
        session[7] = dict(gamemode_roles)

    random.shuffle(massive_role_list)
    for player in session[1]:
        role = massive_role_list.pop()
        session[1][player][1] = role
        if role == 'hunter':
            session[1][player][4].append('hunterbullet')

    for i in range(gamemode_roles['cursed villager'] if 'cursed villager' in gamemode_roles else 0):
        cursed_choices = [x for x in session[1] if get_role(x, 'role') not in\
        ['wolf', 'werecrow', 'seer', 'fool'] and 'cursed' not in session[1][x][3]]
        if cursed_choices:
            cursed = random.choice(cursed_choices)
            session[1][cursed][3].append('cursed')
    for i in range(gamemode_roles['gunner'] if 'gunner' in gamemode_roles else 0):
        if gamemode in ['chaos', 'random']:
            gunner_choices = [x for x in session[1] if 'gunner' not in session[1][x][3]]
        else:
            gunner_choices = [x for x in session[1] if get_role(x, 'role') not in \
            WOLF_ROLES_ORDERED + NEUTRAL_ROLES_ORDERED and 'gunner' not in session[1][x][3]]
        if gunner_choices:
            pewpew = random.choice(gunner_choices)
            session[1][pewpew][3].append('gunner')
            session[1][pewpew][4] += ['bullet'] * int(GUNNER_MULTIPLIER * len(session[1]) + 1)
    if gamemode == 'belunga':
        for player in session[1]:
            session[1][player][4].append('belunga_totem')

async def end_game(reason, winners=None):
    global faftergame
    await client.change_presence(game=client.get_server(WEREWOLF_SERVER).me.game, status=discord.Status.online)
    if not session[0]:
        return
    session[0] = False
    if session[2]:
        if session[3][1]:
            session[4][1] += datetime.now() - session[3][1]
    else:
        if session[3][0]:
            session[4][0] += datetime.now() - session[3][0]
    msg = "<@{}> Game kết thúc! :smiley: Đêm kéo dài **{:02d}:{:02d}**. Ngày kéo dài **{:02d}:{:02d}**. Game kéo dài **{:02d}:{:02d}**. \
          \n{}\n\n".format('> <@'.join(sort_players(session[1])), session[4][0].seconds // 60, session[4][0].seconds % 60,
          session[4][1].seconds // 60, session[4][1].seconds % 60, (session[4][0].seconds + session[4][1].seconds) // 60,
          (session[4][0].seconds + session[4][1].seconds) % 60, reason)
    if not winners == None:
        for player in session[1]:
            # ALTERNATE WIN CONDITIONS
            if session[1][player][0] and get_role(player, 'role') == 'crazed shaman':
                winners.append(player)
        winners = sort_players(winners)
        if len(winners) == 0:
            msg += "Trận hòa!"
        elif len(winners) == 1:
            msg += "Kẻ thắng cuộc là **{}**!".format(get_name(winners[0]))
        elif len(winners) == 2:
            msg += "Kẻ thắng cuộc là **{}** và **{}**! :smiley:".format(get_name(winners[0]), get_name(winners[1]))
        else:
            msg += ":smiley: Kẻ thắng cuộc là **{}**, và **{}**!".format('**, **'.join(map(get_name, winners[:-1])), get_name(winners[-1]))
    await client.send_message(client.get_channel(GAME_CHANNEL), msg)
    await log(1, "WINNERS: {}".format(winners))

    players = list(session[1])
    session[3] = [0, 0]
    session[4] = [timedelta(0), timedelta(0)]
    session[6] = ''
    session[7] = {}

    perms = client.get_channel(GAME_CHANNEL).overwrites_for(client.get_server(WEREWOLF_SERVER).default_role)
    perms.send_messages = True
    await client.edit_channel_permissions(client.get_channel(GAME_CHANNEL), client.get_server(WEREWOLF_SERVER).default_role, perms)
    for player in players:
        member = client.get_server(WEREWOLF_SERVER).get_member(player)
        if member:
            await client.remove_roles(member, PLAYERS_ROLE)
		del session[1][player]

    if faftergame:
        # !faftergame <command> [<parameters>]
        # faftergame.content.split(' ')[0] is !faftergame
        command = faftergame.content.split(' ')[1]
        parameters = ' '.join(faftergame.content.split(' ')[2:])
        await commands[command][0](faftergame, parameters)
        faftergame = None

def win_condition():
    teams = {'village' : 0, 'wolf' : 0, 'neutral' : 0}
    injured_wolves = 0
    for player in session[1]:
        if session[1][player][0]:
            if 'injured' in session[1][player][4]:
                if get_role(player, 'actualteam') == 'wolf' and session[1][player][1] != 'cultist':
                    injured_wolves += 1
            else:
                if session[1][player][1] == 'cultist':
                    teams['village'] += 1
                else:
                    teams[roles[session[1][player][1]][0]] += 1
    winners = []
    win_team = ''
    win_lore = ''
    win_msg = ''
    if len([x for x in session[1] if session[1][x][0]]) == 0:
        win_lore = 'Tất cả mọi người đã chết. Ngôi làng bị bỏ hoang, phai tàn theo thời gian.:cry:'
        win_team = 'no win'
    elif teams['village'] + teams['neutral'] <= teams['wolf']:
        win_team = 'wolf'
        win_lore = 'Số dân khỏe mạnh còn sót lại bằng hoặc ít hơn số sói! Sói áp đảo dân làng và đã thống trị cả ngôi làng!.:skull:'
    elif len([x for x in session[1] if session[1][x][0] and get_role(x, 'role') in ACTUAL_WOLVES + ['traitor']]) == 0:
        # old version: teams['wolf'] == 0 and injured_wolves == 0:
        win_team = 'village'
        win_lore = 'Tất cả sói đã chết! Dân làng quyết định nướng thịt sói để ăn mừng chiến thắng cùng nhau!.:thumpsup:'
    else:
        return None
    
    for player in session[1]:
        if get_role(player, 'actualteam') == win_team:
            winners.append(player)
    return [win_team, win_lore + '\n\n' + end_game_stats(), winners]

def end_game_stats():
    role_msg = ""
    role_dict = {}
    for role in roles:
        role_dict[role] = []
    for player in session[1]:
        if 'traitor' in session[1][player][4]:
            session[1][player][1] = 'traitor'
            session[1][player][4].remove('traitor')
        role_dict[session[1][player][1]].append(player)
        if 'cursed' in session[1][player][3]:
            role_dict['cursed villager'].append(player)
        if 'gunner' in session[1][player][3]:
            role_dict['gunner'].append(player)
    for key in sort_roles(role_dict):
        value = sort_players(role_dict[key])
        if len(value) == 0:
            pass
        elif len(value) == 1:
            role_msg += "**{}** là **{}**. ".format(key, get_name(value[0]))
        elif len(value) == 2:
            role_msg += "**{}** là **{}** và **{}**. ".format(roles[key][1], get_name(value[0]), get_name(value[1]))
        else:
            role_msg += "**{}** là **{}**, và **{}**. ".format(roles[key][1], '**, **'.join(map(get_name, value[:-1])), get_name(value[-1]))
    return role_msg

def get_name(player):
    member = client.get_server(WEREWOLF_SERVER).get_member(player)
    if member:
        return str(member.display_name)
    else:
        return str(player)

def get_player(string):
    string = string.lower()
    users = []
    discriminators = []
    nicks = []
    users_contains = []
    nicks_contains = []
    for player in session[1]:
        if string == player.lower() or string.strip('<@!>') == player:
            return player
        member = client.get_server(WEREWOLF_SERVER).get_member(player)
        if member:
            if member.name.lower().startswith(string):
                users.append(player)
            if string.strip('#') == member.discriminator:
                discriminators.append(player)
            if member.display_name.lower().startswith(string):
                nicks.append(player)
            if string in member.name.lower():
                users_contains.append(player)
            if string in member.display_name.lower():
                nicks_contains.append(player)
        elif get_player(player).lower().startswith(string):
            users.append(player)
    if len(users) == 1:
        return users[0]
    if len(discriminators) == 1:
        return discriminators[0]
    if len(nicks) == 1:
        return nicks[0]
    if len(users_contains) == 1:
        return users_contains[0]
    if len(nicks_contains) == 1:
        return nicks_contains[0]
    return None

def sort_players(players):
    fake = []
    real = []
    for player in players:
        if client.get_server(WEREWOLF_SERVER).get_member(player):
            real.append(player)
        else:
            fake.append(player)
    return sorted(real, key=get_name) + sorted(fake, key=int)

def get_role(player, level):
    # level: {team: reveal team only; actualteam: actual team; seen: what the player is seen as; death: role taking into account cursed and cultist and traitor; actual: actual role}
##(terminology: role = what you are, template = additional things that can be applied on top of your role) 
##cursed, gunner, blessed, mayor, assassin are all templates 
##so you always have exactly 1 role, but can have 0 or more templates on top of that 
##revealing totem (and similar powers, like detective id) only reveal roles
    if player in session[1]:
        role = session[1][player][1]
        templates = session[1][player][3]
        if level == 'team':
            if roles[role][0] == 'wolf':
                if not role in ['cultist', 'traitor']:
                    return "wolf"
            return "villager"
        elif level == 'actualteam':
            return roles[role][0]
        elif level == 'seen':
            seen_role = None
            if role in ROLES_SEEN_WOLF:
                seen_role = 'wolf'
            elif session[1][player][1] in ROLES_SEEN_VILLAGER:
                seen_role = 'villager'
            else:
                seen_role = role
            for template in templates:
                if template in ROLES_SEEN_WOLF:
                    seen_role = 'wolf'
                    break
                if template in ROLES_SEEN_VILLAGER:
                    seen_role = 'villager'
            return seen_role
        elif level == 'death':
            returnstring = ''
            if role == 'traitor':
                returnstring += 'villager'
            else:
                returnstring += role
            return returnstring
        elif level == 'deathstats':
            returnstring = ''
            if role == 'traitor':
                returnstring += 'villager'
            else:
                returnstring += role
            return returnstring
        elif level == 'role':
            return role
        elif level == 'templates':
            return templates
        elif level == 'actual':
            return ' '.join(templates) + ' ' + role
    return None

def get_roles(gamemode, players):
    if gamemode.startswith('roles'):
        role_string = ' '.join(gamemode.split(' ')[1:])
        if role_string != '':
            gamemode_roles = {}
            separator = ','
            if ';' in role_string:
                separator = ';'
            for role_piece in role_string.split(separator):
                piece = role_piece.strip()
                if '=' in piece:
                    role, amount = piece.split('=')
                elif ':' in piece:
                    role, amount = piece.split(':')
                else:
                    return None
                amount = amount.strip()
                if amount.isdigit():
                    gamemode_roles[role.strip()] = int(amount)
            return gamemode_roles
    elif gamemode in gamemodes:
        if players in range(gamemodes[gamemode]['min_players'], gamemodes[gamemode]['max_players'] + 1):
            if gamemode == 'random':
                exit = False
                while not exit:
                    exit = True
                    available_roles = [x for x in roles if x not in TEMPLATES_ORDERED\
                                        and x not in ('villager', 'cultist')]
                    gamemode_roles = dict((x, 0) for x in available_roles)
					gamemode_roles[random.choice(ACTUAL_WOLVES)] += 1 # ensure at least 1 wolf that can kill
                    for i in range(players - 1):
                        gamemode_roles[random.choice(available_roles)] += 1
                    gamemode_roles['gunner'] = random.randrange(int(players ** 1.2 / 4))
                    gamemode_roles['cursed villager'] = random.randrange(int(players ** 1.2 / 3))
                    teams = {'village' : 0, 'wolf' : 0, 'neutral' : 0}
                    for role in gamemode_roles:
                        if role not in TEMPLATES_ORDERED:
                            teams[roles[role][0]] += gamemode_roles[role]
                    if teams['wolf'] >= teams['village'] + teams['neutral']:
                        exit = False
                for role in dict(gamemode_roles):
                    if gamemode_roles[role] == 0:
                        del gamemode_roles[role]
                return gamemode_roles
            else:
                gamemode_roles = {}
                for role in roles:
                    if role in gamemodes[gamemode]['roles'] and gamemodes[gamemode]['roles'][role][\
                    players - MIN_PLAYERS] > 0:
                        gamemode_roles[role] = gamemodes[gamemode]['roles'][role][players - MIN_PLAYERS]
                return gamemode_roles
    return None

def get_votes(totem_dict):
    voteable_players = [x for x in session[1] if session[1][x][0]]
    able_players = [x for x in voteable_players if 'injured' not in session[1][x][4]]
    vote_dict = {'abstain' : 0}
    for player in voteable_players:
        vote_dict[player] = 0
    able_voters = [x for x in able_players if totem_dict[x] == 0]
    for player in able_voters:
        if session[1][player][2] in vote_dict:
            vote_dict[session[1][player][2]] += 1
        if 'influence_totem' in session[1][player][4] and session[1][player][2] in vote_dict:
            vote_dict[session[1][player][2]] += 1
    for player in [x for x in able_players if totem_dict[x] != 0]:
        if totem_dict[player] < 0:
            vote_dict['abstain'] += 1
        else:
            for p in [x for x in voteable_players if x != player]:
                vote_dict[p] += 1
    return vote_dict

def _autocomplete(string, lst):
    if string in lst:
        return (string, 1)
    else:
        choices = []
        for item in lst:
            if item.startswith(string):
                choices.append(item)
        if len(choices) == 1:
            return (choices[0], 1)
        else:
            return (choices, len(choices))

def verify_gamemode(gamemode, verbose=True):
    msg = ''
    good = True
    for i in range(gamemodes[gamemode]['max_players'] - gamemodes[gamemode]['min_players'] + 1):
        total = sum(gamemodes[gamemode]['roles'][role][i + gamemodes[gamemode]['min_players'] - MIN_PLAYERS] for role in gamemodes[gamemode]['roles']\
        if role not in TEMPLATES_ORDERED)
        msg += str(total)
        if total != i + gamemodes[gamemode]['min_players'] and total != 0:
            good = False
            msg += ' - should be ' + str(i + gamemodes[gamemode]['min_players'])
        msg += '\n'
    msg = msg[:-1]
    if verbose:
        return msg
    else:
        return good

def verify_gamemodes(verbose=True):
    msg = ''
    good = True
    for gamemode in sorted(gamemodes):
        msg += gamemode + '\n'
        result = verify_gamemode(gamemode)
        resultlist = result.split('\n')
        for i in range(len(resultlist)):
            if resultlist[i] != str(i + gamemodes[gamemode]['min_players']) and resultlist[i] != '0':
                msg += result
                good = False
                break
        else:
            msg += 'good'
        msg += '\n\n'
    if verbose:
        return msg
    else:
        return good

async def wolfchat(message, author=''):
    if isinstance(message, discord.Message):
        author = message.author.id
        msg = message.content
    else:
        msg = str(message)
        
    member = client.get_server(WEREWOLF_SERVER).get_member(author)
    if member:
        athr = member.display_name
    else:
        athr = author
    for wolf in [x for x in session[1] if x != author and session[1][x][0] and session[1][x][1] in WOLFCHAT_ROLES and client.get_server(WEREWOLF_SERVER).get_member(x)]:
        try:
            pfx = "**-[:wolf:Wolfchat:wolf:]-**"
            if athr != '':
                pfx += " Tin nhắn từ **{}**".format(athr)
            await client.send_message(client.get_server(WEREWOLF_SERVER).get_member(wolf), "{}: {}".format(pfx, msg))
        except discord.Forbidden:
            pass

async def player_idle(message):
    while message.author.id in session[1] and not session[0]:
        await asyncio.sleep(1)
    while message.author.id in session[1] and session[0] and session[1][message.author.id][0]:
        def check(msg):
            if not message.author.id in session[1] or not session[1][message.author.id][0] or not session[0]:
                return True
            if msg.author.id == message.author.id and msg.channel.id == client.get_channel(GAME_CHANNEL).id:
                return True
            return False
        msg = await client.wait_for_message(author=message.author, channel=client.get_channel(GAME_CHANNEL), timeout=PLAYER_TIMEOUT, check=check)
        if msg == None and message.author.id in session[1] and session[0] and session[1][message.author.id][0]:
            await client.send_message(client.get_channel(GAME_CHANNEL), message.author.mention + "**, Bạn đã treo máy hơi lâu rồi đấy. Nói gì trong chat đi nếu không bạn sẽ bị tuyên bố đã chết!.:scream:**")
            try:
                await client.send_message(message.author, "**Bạn đã treo máy trong #" + client.get_channel(GAME_CHANNEL).name + " hơi lâu rồi đấy. Hãy nói gì đó trong chat nếu không bạn sẽ bị tuyên bố đã chết.:joy:**")
            except discord.Forbidden:
                pass
            msg = await client.wait_for_message(author=message.author, channel=client.get_channel(GAME_CHANNEL), timeout=PLAYER_TIMEOUT2, check=check)
            if msg == None and message.author.id in session[1] and session[0] and session[1][message.author.id][0]:
                await client.send_message(client.get_channel(GAME_CHANNEL), "**" + get_name(message.author.id) + "** Ngủ say như chết và.....chết thật :v.:joy: "
                                          "Kẻ còn sống đã chôn **" + get_role(message.author.id, 'death') + '**.')
                if message.author.id in stasis:
                    stasis[message.author.id] += QUIT_GAME_STASIS
                else:
                    stasis[message.author.id] = QUIT_GAME_STASIS
                session[1][message.author.id][0] = False
                try:
                    await client.remove_roles(client.get_server(WEREWOLF_SERVER).get_member(message.author.id), PLAYERS_ROLE)
                except:
                    pass
                await check_traitor()
				await log(1, "{} ({}) IDLE OUT".format(message.author.display_name, message.author.id))

def is_online(user_id):
    member = client.get_server(WEREWOLF_SERVER).get_member(user_id)
    if member:
        if member.status in [discord.Status.online, discord.Status.idle]:
            return True
    return False

async def check_traitor():
    if not session[0] and win_condition() == None:
        return
    for other in [session[1][x][4] for x in session[1]]:
        if 'traitor' in other:
            # traitor already turned
            return
    wolf_team_alive = [x for x in session[1] if session[1][x][0] and get_role(x, 'role') in [
        'wolf', 'werecrow', 'werekitten', 'traitor']]
    wolf_team_no_traitors = [x for x in wolf_team_alive if get_role(x, 'role') != 'traitor']
    if len(wolf_team_no_traitors) == 0:
        if len(wolf_team_alive) == 0:
            # no wolves alive; don't play traitor turn message
            return
        traitors = [x for x in session[1] if session[1][x][0] and get_role(x, 'role') == 'traitor']
        await log(1, ', '.join(traitors) + " turned into wolf")
        for traitor in traitors:
            session[1][traitor][4].append('traitor')
            session[1][traitor][1] = 'wolf'
            member = client.get_server(WEREWOLF_SERVER).get_member(traitor)
            if member:
                try:
                    await client.send_message(member, ":full_moon: HÚuuuuuuuuu...Bạn đã trở thành sói!\nĐã đến lúc báo thù cho những đồng đội đã chết! :smiling_imp:")
                except discord.Forbidden:
                    pass
        await client.send_message(client.get_channel(GAME_CHANNEL), "**Dân làng khi đang ăn mừng chiến thắng, bỗng nghe 1 tiếng hú rợn người. Vẫn còn sói!! :scream:**")        

def sort_roles(role_list):
    role_list = list(role_list)
    result = []
    for role in WOLF_ROLES_ORDERED + VILLAGE_ROLES_ORDERED + NEUTRAL_ROLES_ORDERED + TEMPLATES_ORDERED:
        result += [role] * role_list.count(role)
    return result

async def run_game():
    await client.change_presence(game=client.get_server(WEREWOLF_SERVER).me.game, status=discord.Status.dnd)
    session[0] = True
    session[2] = False
    if session[6] == '':
        vote_dict = {}
        for player in session[1]:
            vote = session[1][player][2]
            if vote in vote_dict:
                vote_dict[vote] += 1
            elif vote != '':
                vote_dict[vote] = 1
        for gamemode in vote_dict:
            if vote_dict[gamemode] >= len(session[1]) // 2 + 1:
                session[6] = gamemode
                break
        else:
            if datetime.now().date() == __import__('datetime').date(2017, 4, 1) or 'belunga' in globals():
                session[6] = 'belunga'
            else:
                session[6] = 'default'
    for player in session[1]:
        session[1][player][1] = ''
        session[1][player][2] = ''
    perms = client.get_channel(GAME_CHANNEL).overwrites_for(client.get_server(WEREWOLF_SERVER).default_role)
    perms.send_messages = False
    await client.edit_channel_permissions(client.get_channel(GAME_CHANNEL), client.get_server(WEREWOLF_SERVER).default_role, perms)
    if not get_roles(session[6], len(session[1])):
        session[6] = 'default' # Fallback if invalid number of players for gamemode or invalid gamemode somehow

	for stasised in [x for x in stasis if stasis[x] > 0]:
        stasis[stasised] -= 1
    await client.send_message(client.get_channel(GAME_CHANNEL), "<@{}>, Chào mừng tới Ma sói, 1 trò chơi nổi tiếng :smiley:. "
                              "Đang dùng chế độ chơi **{}** với **{}** người chơi.\nTất cả người chơi kiểm tra tin nhắn từ tôi để có hướng dẫn.:joy: "
                              "Nếu ko nhận đc tin nhắn, hãy báo {}.:scream:".format('> <@'.join(sort_players(session[1])),
                              session[6], len(session[1]), client.get_server(WEREWOLF_SERVER).get_member(OWNER_ID).name))
    await assign_roles(session[6])
    await game_loop()

async def game_loop(ses=None):
    if ses:
        await client.send_message(client.get_channel(GAME_CHANNEL), PLAYERS_ROLE.mention + ", Chào mừng đến game Ma sói, 1 trờ chơi phổ biến.:smiley: "
                              "Đang dùng chế độ chơi **{}** với **{}** người chơi.\nTất cả người chơi kiểm tra tin nhắn để xem tin nhắn từ tôi.:joy: "
                              "Nếu bạn không nhận được tin nhắn nào, hãy để {} biết.:scream:".format(session[6], len(session[1]), client.get_server(WEREWOLF_SERVER).get_member(OWNER_ID).name))
        globals()['session'] = ses
    await log(1, str(session))
    first_night = True
    # GAME START
    while win_condition() == None and session[0]:
        log_msg = ''
        for player in session[1]:
            member = client.get_server(WEREWOLF_SERVER).get_member(player)
            role = get_role(player, 'role')
            if role in ['shaman', 'crazed shaman'] and session[1][player][0]:
                if role == 'shaman':
                    session[1][player][2] = random.choice(SHAMAN_TOTEMS)
                elif role == 'crazed shaman':
                    session[1][player][2] = random.choice(list(totems))
                log_msg += "{} ({}) HAS {}".format(get_name(player), player, session[1][player][2]) + '\n'
            elif role == 'hunter' and session[1][player][0] and 'hunterbullet' not in session[1][player][4]:
                session[1][player][2] = player
            if first_night:
                await _send_role_info(player)
            else:
                await _send_role_info(player, sendrole=False)
        await log(1, 'SUNSET LOG:\n' + log_msg)
        if session[3][0] == 0:
            first_night = False
        # NIGHT
        session[3][0] = datetime.now()
        await client.send_message(client.get_channel(GAME_CHANNEL), ":full_moon: Bây giờ là **ban đêm**.:full_moon:")
        warn = False
        while win_condition() == None and not session[2] and session[0]:
            end_night = True
            for player in session[1]:
                if session[1][player][0] and session[1][player][1] in ['wolf', 'werecrow', 'werekitten', 'sorcerer',
                                                                       'seer', 'harlot', 'hunter']:
                    end_night = end_night and (session[1][player][2] != '')
                if session[1][player][0] and session[1][player][1] in ['shaman', 'crazed shaman']:
                    end_night = end_night and (session[1][player][2] in session[1])
            end_night = end_night or (datetime.now() - session[3][0]).total_seconds() > NIGHT_TIMEOUT
            if end_night:
                session[2] = True
                session[3][1] = datetime.now() # attempted fix for using !time right as night ends
            if (datetime.now() - session[3][0]).total_seconds() > NIGHT_WARNING and warn == False:
                warn = True
                await client.send_message(client.get_channel(GAME_CHANNEL), "**:full_moon: Một vài dân làng dậy sớm và nhận thấy trời vẫn chưa sáng. "
                                          "Đêm thì sắp tàn mà vẫn còn có tiếng nói chuyện của dân làng.:full_moon:**")
            await asyncio.sleep(0.1)
        night_elapsed = datetime.now() - session[3][0]
        session[4][0] += night_elapsed
        
        # BETWEEN NIGHT AND DAY
        session[3][1] = datetime.now() # fixes using !time screwing stuff up
        killed_msg = ''
        killed_dict = {}
        for player in session[1]:
            killed_dict[player] = 0   
        killed_players = []
        hunter_kill = None
        alive_players = sort_players(x for x in session[1] if session[1][x][0])
        log_msg = "SUNRISE LOG:\n"
        if session[0]:
            for player in alive_players:
                role = get_role(player, 'role')
                if role in ['shaman', 'crazed shaman'] and session[1][player][2] in totems:
                    totem_target = random.choice([x for x in alive_players if x != player])
                    totem = session[1][player][2]
                    session[1][totem_target][4].append(totem)
                    session[1][player][2] = totem_target
                    log_msg += player + '\'s ' + totem + ' given to ' + totem_target + "\n"
                    member = client.get_server(WEREWOLF_SERVER).get_member(player)
                    if member:
                        try:
                            random_given = "wtf? this is a bug; pls report to admins"
                            if role == 'shaman':
                                random_given = "Vì bạn quên không đưa bùa cho ai cả, **{0}** của bạn đã được ngẫu nhiên gửi đến cho **{1}**.:smiling_imp:".format(
                                    totem.replace('_', ' '), get_name(totem_target))
                            elif role == 'crazed shaman':
                                random_given = "Vì bạn quên không đưa bùa cho ai, bùa đã được ngẫu nhiên gửi cho **{0}**.:smiling_imp:".format(get_name(totem_target))
                            await client.send_message(member, random_given)
                        except discord.Forbidden:
                            pass
                elif role == 'harlot' and session[1][player][2] == '':
                    member = client.get_server(WEREWOLF_SERVER).get_member(player)
                    session[1][player][2] = player
                    log_msg += "{0} ({1}) STAY HOME".format(get_name(player), player) + "\n"
                    if member:
                        try:
                            await client.send_message(member, "Bạn sẽ ở nhà đêm nay.")
                        except discord.Forbidden:
                            pass
                elif role == 'hunter' and session[1][player][2] == '':
                    member = client.get_server(WEREWOLF_SERVER).get_member(player)
                    session[1][player][2] = player
                    log_msg += "{0} ({1}) PASS".format(get_name(player), player) + "\n"
                    if member:
                        try:
                            await client.send_message(member, "Bạn đã chọn không giết ai tối nay.:scream:")
                        except discord.Forbidden:
                            pass
        
        # BELUNGA
        for player in [x for x in session[1] if session[1][x][0]]:
            for i in range(session[1][player][4].count('belunga_totem')):
                session[1][player][4].append(random.choice(list(totems) + ['belunga_totem', 'bullet']))
                if random.random() < 0.1 and 'gunner' not in get_role(player, 'templates'):
                    session[1][player][3].append('gunner')

        # Wolf kill
        wolf_votes = {}
        wolf_killed = None
        gunner_revenge = []
        wolf_deaths = []
        wolf_turn = []
        
        for player in alive_players:
            if get_role(player, 'role') in ACTUAL_WOLVES:
                if session[1][player][2] in wolf_votes:
                    wolf_votes[session[1][player][2]] += 1
                elif session[1][player][2] != "":
                    wolf_votes[session[1][player][2]] = 1
        if wolf_votes != {}:
            max_votes = max([wolf_votes[x] for x in wolf_votes])
            temp_players = []
            for target in wolf_votes:
                if wolf_votes[target] == max_votes:
                    temp_players.append(target)
            if len(temp_players) == 1:
                wolf_killed = temp_players[0]
                log_msg += "WOLFKILL: {} ({})".format(get_name(wolf_killed), wolf_killed) + "\n"
                if get_role(wolf_killed, 'role') == 'harlot' and session[1][wolf_killed][2] != wolf_killed:
                    killed_msg += "Nạn nhân của sói không ở nhà đêm nay và né được đòn tấn công của sói.:joy:\n"
                else:
                    killed_dict[wolf_killed] += 1
                    wolf_deaths.append(wolf_killed)

        # Harlot stuff
        for harlot in [x for x in alive_players if get_role(x, 'role') == 'harlot']:
            visited = session[1][harlot][2]
            if visited != harlot:
                if visited == wolf_killed and not 'protection_totem' in session[1][visited][4]:
                    killed_dict[harlot] += 1
                    killed_msg += "**{}** đã chết vào đêm qua.:skull: ".format(get_name(harlot))
                    wolf_deaths.append(harlot)
                elif visited in [x for x in session[1] if get_role(x, 'role') in ACTUAL_WOLVES]:
                    killed_dict[harlot] += 1
                    killed_msg += "**{}** đã chết vào đêm qua.:skull:\n".format(get_name(harlot))
                    wolf_deaths.append(harlot)
        
        # Hunter stuff
        for hunter in [x for x in session[1] if get_role(x, 'role') == 'hunter']:
            target = session[1][hunter][2]
            if target not in [hunter, '']:
                if 'hunterbullet' in session[1][hunter][4]:
                    session[1][hunter][4].remove('hunterbullet')
                    killed_dict[target] += 100

        
        # Totem stuff
        totem_holders = []
        protect_totemed = []
        death_totemed = []
        revengekill = ""
        
        for player in sort_players(session[1]):
            if len([x for x in session[1][player][4] if x in totems]) > 0:
                totem_holders.append(player)
            prot_tots = 0
            death_tots = 0
            death_tots += session[1][player][4].count('death_totem')
            killed_dict[player] += death_tots
            if get_role(player, 'role') != 'harlot' or session[1][player][2] == player:
                # fix for harlot with protect
                prot_tots = session[1][player][4].count('protection_totem')
                killed_dict[player] -= prot_tots
            if wolf_killed == player and 'protection_totem' in session[1][player][4] and killed_dict[player] < 1:
                protect_totemed.append(player)
            if 'death_totem' in session[1][player][4] and killed_dict[player] > 0 and death_tots - prot_tots > 0:
                death_totemed.append(player)

            if 'cursed_totem' in session[1][player][4]:
                if 'cursed' not in get_role(player, 'templates'):
                    session[1][player][3].append('cursed')

            if player in wolf_deaths and killed_dict[player] > 0 and player not in death_totemed:
                # player was targeted and killed by wolves
                if session[1][player][4].count('lycanthropy_totem') > 0:
                    killed_dict[player] = 0
                    wolf_turn.append(player)
                    await wolfchat("{} is now a **wolf**!".format(get_name(player)))
                    try:
                        member = client.get_server(WEREWOLF_SERVER).get_member(player)
                        if member:
                            await client.send_message(member, "Bạn tỉnh dậy và thấy đau nhói, bạn nhận ra bạn đã bị tấn công bởi sói :scream: "
                                                              "Bùa bạn đang giữ cháy sáng :fire: , và bạn biến thành sói! :scream:")
                    except discord.Forbidden:
                        pass
                elif session[1][player][4].count('retribution_totem') > 0:
                    revenge_targets = [x for x in session[1] if session[1][x][0] and get_role(x, 'role') in [
                        'wolf', 'werecrow', 'werekitten']]
                    if get_role(player, 'role') == 'harlot' and get_role(session[1][player][2], 'role') in [
                        'wolf', 'werecrow', 'werekitten']:
                        revenge_targets[:] = [session[1][player][2]]
                    else:
                        revenge_targets[:] = [x for x in revenge_targets if session[1][x][2] == wolf_killed]
                    revengekill = random.choice(revenge_targets)
                    killed_dict[revengekill] += 100
                    if killed_dict[revengekill] > 0:
                        killed_msg += "Khi bị tấn công vào đêm qua, **{}** cầm lá bùa đang cháy sáng :fire:. Thi thể của **{}**".format(
                                        get_name(wolf_killed), get_name(revengekill))
                        killed_msg += ", được tìm thấy ở hiện trường.:skull:\n".format(get_role(revengekill, 'role'))

            other = session[1][player][4][:]
            for o in other[:]:
                # hacky way to get specific totems to last 2 nights
                if o in ['death_totem', 'protection_totem', 'cursed_totem', 'retribution_totem', 'lycanthropy_totem2',
                         'deceit_totem2']:
                    other.remove(o)
                elif o == 'lycanthropy_totem':
                    other.remove(o)
                    other.append('lycanthropy_totem2')
                elif o == 'deceit_totem':
                    other.remove(o)
                    other.append('deceit_totem2')
            session[1][player][4] = other
        for player in sort_players(wolf_deaths):
            if 'gunner' in get_role(player, 'templates') and \
            session[1][player][4].count('bullet') > 0 and killed_dict[player] > 0:
                if random.random() < GUNNER_REVENGE_WOLF:
                    revenge_targets = [x for x in session[1] if session[1][x][0] and get_role(x, 'role') in [
                        'wolf', 'werecrow', 'werekitten']]
                    if get_role(player, 'role') == 'harlot' and get_role(session[1][player][2], 'role') in [
                        'wolf', 'werecrow', 'werekitten']:
                        revenge_targets[:] = [session[1][player][2]]
                    else:
                        revenge_targets[:] = [x for x in revenge_targets if session[1][x][2] == wolf_killed]
                    revenge_targets[:] = [x for x in revenge_targets if x not in gunner_revenge]
                    if revenge_targets:
                        target = random.choice(revenge_targets)
                        gunner_revenge.append(target)
                        session[1][player][4].remove('bullet')
                        killed_dict[target] += 100
                        if killed_dict[target] > 0:
                            killed_msg += "May thay **{}** có súng và đạn nên **{}** bị bắn chết.:joy:\n".format(
                                get_name(player), get_name(target), get_role(target, 'death'))
                if session[1][player][4].count('bullet') > 0:
                    give_gun_targets = [x for x in session[1] if session[1][x][0] and get_role(x, 'role') in WOLFCHAT_ROLES]
                    if len(give_gun_targets) > 0:
                        give_gun = random.choice(give_gun_targets)
                        if not 'gunner' in get_role(give_gun, 'templates'):
                            session[1][give_gun][3].append('gunner')
                        session[1][give_gun][4].append('bullet')
                        member = client.get_server(WEREWOLF_SERVER).get_member(give_gun)
                        if member:
                            try:
                                await client.send_message(member, "Khi đang lục lọi nhà của **{}**, bạn tìm thấy 1 khẩu súng được nạp 1 "
                                "viên đạn bạc! Bạn chỉ có thể xài súng vào ban ngày. Nếu bạn bắn trúng sói, bạn sẽ cố tình bắt trượt. Nếu "
                                "bạn bắn dân làng, khả năng cao là họ sẽ bị thương.".format(get_name(player)))
                            except discord.Forbidden:
                                pass
            
        for player in killed_dict:
            if killed_dict[player] > 0:
                killed_players.append(player)

        killed_players = sort_players(killed_players)
        
        for player in killed_players:
            member = client.get_server(WEREWOLF_SERVER).get_member(player)
            if member:
                await client.remove_roles(member, PLAYERS_ROLE)

        killed_temp = killed_players[:]

        log_msg += "PROTECT_TOTEMED: " + ", ".join("{} ({})".format(get_name(x), x) for x in protect_totemed) + "\n"
        log_msg += "DEATH_TOTEMED: " + ", ".join("{} ({})".format(get_name(x), x) for x in death_totemed) + "\n"
        log_msg += "PLAYERS TURNED WOLF: " + ", ".join("{} ({})".format(get_name(x), x) for x in wolf_turn) + "\n"
        if revengekill:
            log_msg += "RETRIBUTED: " + "{} ({})\n".format(get_name(revengekill), revengekill)
        if gunner_revenge:
            log_msg += "GUNNER_REVENGE: " + ", ".join("{} ({})".format(get_name(x), x) for x in gunner_revenge) + "\n"
        log_msg += "DEATHS FROM WOLF: " + ", ".join("{} ({})".format(get_name(x), x) for x in wolf_deaths) + "\n"
        log_msg += "KILLED PLAYERS: " + ", ".join("{} ({})".format(get_name(x), x) for x in killed_players) + "\n"

        await log(1, log_msg)
        
        if protect_totemed != []:
            for protected in sort_players(protect_totemed):
                killed_msg += "**{0}** bị tấn công đêm qua, nhưng lá bùa của họ đã cháy sáng :fire:, gây chói lóa kẻ sát nhân giúp họ chạy trốn.:joy:\n".format(
                                    get_name(protected))
        if death_totemed != []:
            for ded in sort_players(death_totemed):
                killed_msg += "**{0}** giữ một lá bùa đang bùng cháy :fire:. Thi thể của **{0}** được phát hiện tại hiện trường.:skull:\n".format(
                                    get_name(ded), get_role(ded, 'death'))
                killed_players.remove(ded)
        if revengekill != "" and revengekill in killed_players:
            # retribution totem
            killed_players.remove(revengekill)
        
        for player in gunner_revenge:
            if player in killed_players:
                killed_players.remove(player)

        if len(killed_players) == 0:
            if protect_totemed == [] and death_totemed == [] and get_role(wolf_killed, 'role') != 'harlot':
                killed_msg += random.choice(lang['nokills']) + '\n'
        elif len(killed_players) == 1:
            killed_msg += ":skull: Thi thể của **{}** được phát hiện. Ai nấy đều xót xa.:cry:\n".format(get_name(killed_players[0]), get_role(killed_players[0], 'death'))
        else:
            killed_msg += ":skull: Thi thể của **{}**, và **{}** được tìm thấy. Dân làng than khóc.:cry:\n".format(
                '**, **'.join(get_name(x) + '**,' + get_role(x, 'death') for x in killed_players[:-1]), get_name(killed_players[-1]), get_role(killed_players[-1], 'death'))

        if session[0] and win_condition() == None:
            await client.send_message(client.get_channel(GAME_CHANNEL), ":full_moon: Đêm tối dài **{0:02d}:{1:02d}**. Dân làng thức dậy và tìm kiếm khắp làng.\n\n{2}".format(
                                                                                    night_elapsed.seconds // 60, night_elapsed.seconds % 60, killed_msg))
        if session[0] and win_condition() == None:
            totem_holders = sort_players(totem_holders)
            if len(totem_holders) == 0:
                pass
            elif len(totem_holders) == 1:
                await client.send_message(client.get_channel(GAME_CHANNEL), random.choice(lang['hastotem']).format(get_name(totem_holders[0])))
            elif len(totem_holders) == 2:
                await client.send_message(client.get_channel(GAME_CHANNEL), random.choice(lang['hastotem2']).format(get_name(totem_holders[0]), get_name(totem_holders[1])))
            else:
                await client.send_message(client.get_channel(GAME_CHANNEL), random.choice(lang['hastotems']).format('**, **'.join([get_name(x) for x in totem_holders[:-1]]), get_name(totem_holders[-1])))

        for player in killed_temp:
            session[1][player][0] = False

        for player in wolf_turn:
            session[1][player][1] = 'wolf'
        
        for player in session[1]:
            session[1][player][2] = ''
            
        if session[0] and win_condition() == None:
            await check_traitor()
            
        # DAY
        session[3][1] = datetime.now()
        if session[0] and win_condition() == None:
            await client.send_message(client.get_channel(GAME_CHANNEL), ":sun_with_face: Bây giờ là **ban ngày**. dùng `{}lynch <player>` đều bầu giết <player>. :smiley:".format(BOT_PREFIX))

        for player in session[1]:
            if session[1][player][0] and 'blinding_totem' in session[1][player][4]:
                if 'injured' not in session[1][player][4]:
                    session[1][player][4].append('injured')
                    for i in range(session[1][player][4].count('blinding_totem')):
                        session[1][player][4].remove('blinding_totem')
                    try:
                        member = client.get_server(WEREWOLF_SERVER).get_member(player)
                        if member:
                            await client.send_message(member, ":dizzy_face: Lá bùa bạn đang cầm bùng cháy. "
                                                              "Bạn thấy lóa mắt và có vẻ như nó sẽ không khỏi "
                                                              "nên bạn đi nghỉ...:dizzy_face:")
                    except discord.Forbidden:
                        pass

        lynched_player = None
        warn = False
        totem_dict = {} # For impatience and pacifism        
        while win_condition() == None and session[2] and lynched_player == None and session[0]:
            for player in [x for x in session[1]]:
                totem_dict[player] = session[1][player][4].count('impatience_totem') - session[1][player][4].count('pacifism_totem')
            vote_dict = get_votes(totem_dict)
            if vote_dict['abstain'] >= len([x for x in session[1] if session[1][x][0] and 'injured' not in session[1][x][4]]) / 2:
                lynched_player = 'abstain'
            max_votes = max([vote_dict[x] for x in vote_dict])
            max_voted = []
            if max_votes >= len([x for x in session[1] if session[1][x][0] and 'injured' not in session[1][x][4]]) // 2 + 1:
                for voted in vote_dict:
                    if vote_dict[voted] == max_votes:
                        max_voted.append(voted)
                lynched_player = random.choice(max_voted)
            if (datetime.now() - session[3][1]).total_seconds() > DAY_TIMEOUT:
                session[3][0] = datetime.now() # hopefully a fix for time being weird
                session[2] = False
            if (datetime.now() - session[3][1]).total_seconds() > DAY_WARNING and warn == False:
                warn = True
                await client.send_message(client.get_channel(GAME_CHANNEL), "**:smiling_imp: Khi dân làng nhận ra mặt trời đã gần khuất núi "
                                          "ánh chiều tà ngả dần sang bóng tối, họ nhận ra rằng còn rất ít thời gian để thống nhất nên treo "
                                          "ai; Nếu họ không thống nhất thì đa số sẽ thắng thiểu số. Và sẽ không ai bị treo nếu "
                                          "không ai bầu hoặc vote hòa nhau.:smiling_imp:**")
            await asyncio.sleep(0.1)
        if not lynched_player and win_condition() == None and session[0]:
            vote_dict = get_votes(totem_dict)
            max_votes = max([vote_dict[x] for x in vote_dict])
            max_voted = []
            for voted in vote_dict:
                if vote_dict[voted] == max_votes and voted != 'abstain':
                    max_voted.append(voted)
            if len(max_voted) == 1:
                lynched_player = max_voted[0]
        if session[0]:
            session[3][0] = datetime.now() # hopefully a fix for time being weird
            day_elapsed = datetime.now() - session[3][1]
            session[4][1] += day_elapsed
        lynched_msg = ""
        if lynched_player and win_condition() == None and session[0]:
            if lynched_player == 'abstain':
                for player in [x for x in totem_dict if session[1][x][0] and totem_dict[x] < 0]:
                    lynched_msg += "**{}** không muốn bầu treo cổ hôm nay :pray:.\n".format(get_name(player))
                lynched_msg += "Dân làng hùa nhau éo treo ai :rage:."
                await client.send_message(client.get_channel(GAME_CHANNEL), lynched_msg)
            else:
                for player in [x for x in totem_dict if session[1][x][0] and totem_dict[x] > 0 and x != lynched_player]:
                    lynched_msg += "**{}** đã nóng vội bầu treo cổ **{}** :dizzy_face:.\n".format(get_name(player), get_name(lynched_player))
                lynched_msg += '\n'
                if 'revealing_totem' in session[1][lynched_player][4]:
                    lynched_msg += ':scream: Khi dân làng đang chuẩn bị treo cổ **{0}**, Là bùa của họ bùng cháy! Khi dân làng hết bị lóa mắt, '
                    lynched_msg += 'họ nhận ra {0} đã trốn thoát! Lá bùa bị bỏ lại nói rằng kẻ trốn thoát là **{1}** :scream:.'
                    lynched_msg = lynched_msg.format(get_name(lynched_player), get_role(lynched_player, 'role'))
                    await client.send_message(client.get_channel(GAME_CHANNEL), lynched_msg)
                else:
                    lynched_msg += random.choice(lang['lynched']).format(get_name(lynched_player))
                    await client.send_message(client.get_channel(GAME_CHANNEL), lynched_msg)
                    session[1][lynched_player][0] = False
                    member = client.get_server(WEREWOLF_SERVER).get_member(lynched_player)
                    if member:
                        await client.remove_roles(member, PLAYERS_ROLE)
                if get_role(lynched_player, 'role') == 'fool' and 'revealing_totem' not in session[1][lynched_player][4]:
                    win_msg = ":joy: Chúc mừng! Các bạn đã treo cổ thằng ngu! Nó thắng rồi ahihi! :joy:\n\n" + end_game_stats()
                    await end_game(win_msg, [lynched_player])
                    return
        elif lynched_player == None and win_condition() == None and session[0]:
            await client.send_message(client.get_channel(GAME_CHANNEL), "Không đủ phiếu bầu để treo cổ.:wave:")
        # BETWEEN DAY AND NIGHT
        session[2] = False
        if session[0] and win_condition() == None:
            await client.send_message(client.get_channel(GAME_CHANNEL), ":zzz: Ngày kéo dài **{0:02d}:{1:02d}**. Dân làng vì quá mệt mỏi nên đã đi ngủ.:zzz:".format(
                                                                  day_elapsed.seconds // 60, day_elapsed.seconds % 60))
            for player in session[1]:
                session[1][player][4][:] = [x for x in session[1][player][4] if x not in [
                    'revealing_totem', 'influence_totem', 'impatience_totem', 'pacifism_totem', 'injured']]
                session[1][player][2] = ''
                
        if session[0] and win_condition() == None:
            await check_traitor()
            
    if session[0]:
        win_msg = win_condition()
        await end_game(win_msg[1], win_msg[2])

async def start_votes(player):
    start = datetime.now()
    while (datetime.now() - start).total_seconds() < 60:
        votes_needed = max(2, min(len(session[1]) // 4 + 1, 4))
        votes = len([x for x in session[1] if session[1][x][1] == 'start'])
        if votes >= votes_needed or session[0] or votes == 0:
            break
        await asyncio.sleep(0.1)
    else:
        for player in session[1]:
            session[1][player][1] = ''
        await client.send_message(client.get_channel(GAME_CHANNEL), "Không đủ phiếu bắt đầu game, bắt đầu bầu lại.")
        
async def rate_limit(message):
    if not (message.channel.is_private or message.content.startswith(BOT_PREFIX)) or message.author.id in ADMINS or message.author.id == OWNER_ID:
        return False
    global ratelimit_dict
    global IGNORE_LIST
    if message.author.id not in ratelimit_dict:
        ratelimit_dict[message.author.id] = 1
    else:
        ratelimit_dict[message.author.id] += 1
    if ratelimit_dict[message.author.id] > IGNORE_THRESHOLD:
        if not message.author.id in IGNORE_LIST:
            IGNORE_LIST.append(message.author.id)
            await log(2, message.author.name + " (" + message.author.id + ") was added to the ignore list for rate limiting.")
        try:
            await reply(message, "Bạn đã xài {0} lệnh trong {1} giây; Tôi sẽ bơ bạn đến hết game.:rage:".format(IGNORE_THRESHOLD, TOKEN_RESET))
        except discord.Forbidden:
            await client.send_message(client.get_channel(GAME_CHANNEL), message.author.mention +
                                      " xài {0} lệnh trong {1} giây và bạn sẽ bị bơ đến cuối game.:rage:".format(IGNORE_THRESHOLD, TOKEN_RESET))
        finally:
            return True
    if message.author.id in IGNORE_LIST or ratelimit_dict[message.author.id] > TOKENS_GIVEN:
        if ratelimit_dict[message.author.id] > TOKENS_GIVEN:
            await log(2, "Ignoring message from " + message.author.name + " (" + message.author.id + "): `" + message.content + "` since no tokens remaining")
        return True
    return False

async def do_rate_limit_loop():
    await client.wait_until_ready()
    global ratelimit_dict
    while not client.is_closed:
        for user in ratelimit_dict:
            ratelimit_dict[user] = 0
        await asyncio.sleep(TOKEN_RESET)

async def game_start_timeout_loop():
    session[5] = datetime.now()
    while not session[0] and len(session[1]) > 0 and datetime.now() - session[5] < timedelta(seconds=GAME_START_TIMEOUT):
        await asyncio.sleep(0.1)
    if not session[0] and len(session[1]) > 0:
        session[0] = True
        await client.change_presence(game=client.get_server(WEREWOLF_SERVER).me.game, status=discord.Status.online)
        await client.send_message(client.get_channel(GAME_CHANNEL), "{0}, Game chờ quá lâu để bắt đầu nên đã bị hủy. "
                          "Nếu bạn còn ở đây và vẫn muốn chơi, hãy gõ `..join` lần nữa.".format(PLAYERS_ROLE.mention))
        perms = client.get_channel(GAME_CHANNEL).overwrites_for(client.get_server(WEREWOLF_SERVER).default_role)
        perms.send_messages = True
        await client.edit_channel_permissions(client.get_channel(GAME_CHANNEL), client.get_server(WEREWOLF_SERVER).default_role, perms)
        for player in list(session[1]):
            del session[1][player]
            member = client.get_server(WEREWOLF_SERVER).get_member(player)
            if member:
                await client.remove_roles(member, PLAYERS_ROLE)
        session[0] = False
        session[3] = [0, 0]
        session[4] = [timedelta(0), timedelta(0)]
        session[6] = ''
        session[7] = {}

async def backup_settings_loop():
    while not client.is_closed:
        print("BACKING UP SETTINGS")
        with open(NOTIFY_FILE, 'w') as notify_file:
            notify_file.write(','.join([x for x in notify_me if x != '']))
        with open(STASIS_FILE, 'w') as stasis_file:
            json.dump(stasis, stasis_file)
        await asyncio.sleep(BACKUP_INTERVAL)

############## POST-DECLARATION STUFF ###############
COMMANDS_FOR_ROLE = {'see' : ['seer'],
                     'kill' : ['wolf', 'werecrow', 'werekitten', 'hunter'],
                     'give' : ['shaman'],
                     'visit' : ['harlot'],
                     'shoot' : ['gunner'],
                     'observe' : ['werecrow', 'sorcerer'],
                     'pass' : ['harlot', 'hunter'],
                     'id' : ['detective']}
GAMEPLAY_COMMANDS = ['join', 'j', 'start', 'vote', 'lynch', 'v', 'abstain', 'abs', 'nl', 'stats', 'leave', 'q', 'role', 'roles']
GAMEPLAY_COMMANDS += list(COMMANDS_FOR_ROLE)

# {role name : [team, plural, description]}
roles = {'wolf' : ['wolf', 'wolves', "Mục tiêu của bạn là giết hết tất cả dân làng. Gõ `kill <player>` trong tin nhắn với bot để giết người bạn chọn."],
         'werecrow' : ['wolf', 'werecrows', "Bạn theo phe sói. Dùng `observe <player>` vào ban đêm để xem người bạn chọn có đang trên giường hay không. "
                                            "Bạn cũng có thể xài `kill <player>` để giết người bạn chọn."],
         'werekitten' : ['wolf', 'werekittens', "Bạn thuộc sói-squad. Nhưng vì bạn quá dễ thương :3 nên nếu bị soi bạn sẽ không khả nghi "
                                                "và kẻ có súng sẽ luôn bắn trượt bạn. Dùng `kill <player>` trong tin nhắn riêng với bot "
                                                "để bầu chọn giết <player>."],
         'traitor' : ['wolf', 'traitors', "Bạn giống y hệt dân làng, nhưng bạn theo phe sói. Chỉ có thám tử mới có thể lật tẩy danh tính "
                                          "thật. Khi tất cả sói chết, bạn trở thành sói."],
         'sorcerer' : ['wolf', 'sorcerers', "Bạn có thể dùng lệnh `observe <player>` trong tin nhắn riêng với bot vào ban đêm để xem người đó "
                                            "có phải là tiên tri hay không. Bạn sẽ không bị soi bởi tiên tri và chỉ có detective mới có thể soi ra bạn."],
         'cultist' : ['wolf', 'cultists', "Vai trò của bạn là hỗ trợ phe sói giết hết dân làng."],
         'seer' : ['village', 'seers', "Vai trò của bạn là nhận diện sói; Bạn có 1 lần soi mỗi đêm. Gõ `see <player>` trong tin nhắn riêng với bot để xem vai người bạn chọn."],
         'shaman' : ['village', 'shamans', "Bạn chọn 1 người mỗi đêm để đưa bùa chú bằng lệnh `give <player>`. Bạn có thể tự cho mình bùa, nhưng bạn không cho cùng 1"
                                           " người bùa 2 đêm liên tiếp. Nếu bạn không xài lệnh, bùa sẽ được phát ngẫu nhiên. "
                                           "Để xem bùa mình đang có, dùng lệnh `myrole`."],
         'harlot' : ['village', 'harlots', "Bạn có thể 'ngủ' cùng 1 người mỗi đêm bằng lệnh `visit <player>`. Nếu bạn ngủ cùng mục tiêu của sói, hay ngủ cùng sói, "
                                           "bạn sẽ chết. Bạn có thể tự ngủ với chính mình để ở nhà."],
         'hunter' : ['village', 'hunters', "Vai trò của bạn là giúp giết hết sói. Mỗi game bạn có thể giết 1 người sử dụng lệnh `kill <player>`. "
                                           "Nếu không muốn giết ai đêm nay, dùng lệnh `pass`."],
         'detective' : ['village', 'detectives', "Nhiệm vụ của bạn là chỉ ra sói và kẻ phản bội (traitor). Vào BUỔI SÁNG, bạn có thể xài `id <player>` trong tin nhắn riêng với bot "
                                                 "để xác định vai người được chọn. Nhưng bạn sẽ có {}% khả năng bị lộ vai cho phe sói mỗi lần bạn sử dụng lệnh.".format(int(DETECTIVE_REVEAL_CHANCE * 100))],
         'villager' : ['village', 'villagers', "Khả năng đặc biệt nhất, chết khi bị giết. Ngoài ra éo có gì đặc biệt hơn. Bạn giúp dân làng bắt sói."],
         'crazed shaman' : ['neutral', 'crazed shamans', "Bạn chọn 1 người để đưa bùa ngẫu nhiên bằng lệnh `give <player>`. Bạn có thể đưa bùa cho chính mình, "
                                                         "nhưng không thể đưa 1 người 2 đêm liên tiếp. Nếu bạn không đưa bùa cho ai, "
                                                         "bùa sẽ được phát ngẫu nhiên. Bạn thắng nếu bạn còn sống ở cuối game."],
         'fool' : ['neutral', 'fools', "Bạn là người thắng nếu bạn bị treo cổ vào buổi sáng. Nếu không thì thua."],
         'cursed villager' : ['template', 'cursed villagers', "Vai này bị ẩn và tiên tri sẽ coi người bị nguyền là sói. Các vai của sói, tiên tri, và thằng ngu không thể bị nguyền."],
         'gunner' : ['template', 'gunners', "Vai này cho người chơi 1 khẩu súng lục. Gõ `shoot <player>` ở ROOM CHAT vào BAN NGÀY để giết <player>. "
                                            "Nếu bạn là dân và bắn sói, nó sẽ chết. Nếu không, sẽ có khả năng giết họ, gây chấn thương "
                                            ", hoặc súng nổ tung. Nếu bạn là sói mà bắn sói, bạn sẽ cố ý bắn trượt."]}

gamemodes = {
    'default' : {
        'description' : "Gamemode mặc định.",
        'min_players' : 4,
        'max_players' : 20,
        'roles' : {
            #4, 5, 6, 7, 8, 9, 10,11,12,13,14,15,16,17,18,19,20
            'wolf' :
            [1, 1, 1, 1, 1, 1,  1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2],
            'werecrow' :
            [0, 0, 0, 0, 0, 0,  0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'werekitten' :
            [0, 0, 0, 0, 0, 0,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'traitor' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'sorcerer' :
            [0, 0, 0, 0, 0, 0,  0, 0, 1, 1, 1, 1, 0, 0, 0, 0, 1],
            'cultist' :
            [0, 0, 0, 1, 0, 0,  0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0],
            'seer' :
            [1, 1, 1, 1, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2],
            'shaman' :
            [0, 0, 0, 1, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2],
            'harlot' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'hunter' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1],
            'detective' :
            [0, 0, 0, 0, 0, 0,  0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'villager' :
            [2, 3, 4, 3, 3, 3,  3, 4, 3, 3, 4, 4, 4, 5, 5, 6, 5],
            'crazed shaman' :
            [0, 0, 0, 0, 0, 1,  1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
            'cursed villager' :
            [0, 0, 1, 1, 1, 1,  1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 3],
            'gunner' :
            [0, 0, 0, 0, 0, 0,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]}
        },
    'test' : {
        'description' : "Gamemode thử nghiệm, nên ko dùng.",
        'min_players' : 5,
        'max_players' : 20,
        'roles' : {
            #4, 5, 6, 7, 8, 9, 10,11,12,13,14,15,16,17,18,19,20
            'wolf' :
            [1, 1, 1, 1, 1, 1,  1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2],
            'werecrow' :
            [0, 0, 0, 0, 0, 0,  0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'werekitten' :
            [0, 0, 0, 0, 0, 0,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'traitor' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'sorcerer' :
            [0, 0, 0, 0, 0, 0,  0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 1],
            'cultist' :
            [0, 0, 0, 1, 0, 0,  0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0],
            'seer' :
            [1, 1, 1, 1, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2],
            'shaman' :
            [0, 0, 0, 1, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2],
            'harlot' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'hunter' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1],
            'detective' :
            [0, 0, 0, 0, 0, 0,  0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'villager' :
            [2, 3, 4, 3, 3, 3,  3, 4, 3, 3, 4, 4, 4, 5, 5, 6, 5],
            'crazed shaman' :
            [0, 0, 0, 0, 0, 1,  1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2],
			'fool' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'cursed villager' :
            [0, 0, 1, 1, 1, 1,  1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 3],
            'gunner' :
            [0, 0, 0, 0, 0, 0,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]}
    },
    'foolish' : {
        'description' : "Cẩn thận, vì thằng ngu có thể nhảy ra từ bất kì đâu để cướp chiến thắng!.",
        'min_players' : 8,
        'max_players' : 20,
        'roles' : {
            #4, 5, 6, 7, 8, 9, 10,11,12,13,14,15,16,17,18,19,20
            'wolf' :
            [0, 0, 0, 0, 1, 1,  2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3],
            'werecrow' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            'werekitten' :
            [0, 0, 0, 0, 0, 0,  0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'traitor' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'sorcerer' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1],
            'cultist' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            'seer' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'shaman' :
            [0, 0, 0, 0, 0, 0,  0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2],
            'harlot' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2],
            'hunter' :
            [0, 0, 0, 0, 0, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'detective' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1],
            'villager' :
            [0, 0, 0, 0, 3, 3,  3, 2, 2, 3, 4, 3, 4, 3, 4, 5, 5],
            'crazed shaman' :
            [0, 0, 0, 0, 0, 0,  0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'fool' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'cursed villager' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            'gunner' :
            [0, 0, 0, 0, 0, 0,  0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1]}
    },
    'chaos' : {
        'description' : "Hỗn loạn và khó lường. Bất cứ ai, kể cả sói, đều có thể sở hữu súng.",
        'min_players' : 4,
        'max_players' : 16,
        'roles' : {
            #4, 5, 6, 7, 8, 9, 10,11,12,13,14,15,16
            'wolf' :
            [1, 1, 1, 1, 1, 1,  2, 2, 2, 3, 3, 3, 3],
            'traitor' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 2, 2],
            'cultist' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'seer' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'shaman' :
            [3, 4, 4, 4, 3, 4,  3, 2, 3, 1, 2, 1, 1],
            'harlot' :
            [0, 0, 0, 1, 1, 1,  2, 2, 2, 3, 3, 3, 4],
            'villager' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'crazed shaman' :
            [0, 0, 0, 0, 1, 1,  1, 2, 2, 3, 3, 4, 4],
            'fool' :
            [0, 0, 1, 1, 1, 1,  1, 2, 2, 2, 2, 2, 2],
            'cursed villager' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'gunner' :
            [1, 1, 1, 1, 1, 2,  2, 2, 2, 3, 3, 3, 3]}
    },
    'orgy' : {
        'description' : "Cẩn thận người bạn sẽ ăn nằm cùng đêm nay! ( ͡° ͜ʖ ͡°)",
        'min_players' : 4,
        'max_players' : 16,
        'roles' : {
            #4, 5, 6, 7, 8, 9, 10,11,12,13,14,15,16
            'wolf' :
            [1, 1, 1, 1, 1, 1,  2, 2, 2, 3, 3, 3, 3],
            'traitor' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 1, 2, 2],
            'cultist' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'seer' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'shaman' :
            [0, 0, 0, 1, 1, 1,  2, 2, 2, 3, 3, 3, 4],
            'harlot' :
            [3, 4, 4, 4, 3, 4,  3, 2, 3, 1, 2, 1, 1],
            'villager' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'crazed shaman' :
            [0, 0, 0, 0, 1, 1,  1, 2, 2, 3, 3, 4, 4],
            'fool' :
            [0, 0, 1, 1, 1, 1,  1, 2, 2, 2, 2, 2, 2],
            'cursed villager' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0]}
    },
    'crazy' : {
        'description' : "Thật nhiều bùa chú ngẫu nhiên!.",
        'min_players' : 4,
        'max_players' : 16,
        'roles' : {
            #4, 5, 6, 7, 8, 9, 10,11,12,13,14,15,16
            'wolf' :
            [1, 1, 1, 1, 1, 1,  1, 1, 2, 2, 1, 1, 2],
            'traitor' :
            [0, 0, 0, 0, 1, 1,  1, 1, 1, 1, 2, 2, 2],
            'cultist' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'seer' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'shaman' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'harlot' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'villager' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'crazed shaman' :
            [3, 4, 5, 6, 5, 6,  7, 7, 7, 8, 8, 9, 9],
            'fool' :
            [0, 0, 0, 0, 1, 1,  1, 2, 2, 2, 3, 3, 3],
            'cursed villager' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0]}
    },
    'belunga' : {
        'description' : "Gamemode điên khùng cho ngày cá tháng tư =)).",
        'min_players' : 4,
        'max_players' : 20,
        'roles' : {}
        },
    'random' : {
        'description' : "Ngoài việc đảm bảo trò chơi sẽ không kết thúc ngay lập tức, chả ai biết sẽ có vai nào xuất hiện.",
        'min_players' : 8,
        'max_players' : 16,
        'roles' : {
            #4, 5, 6, 7, 8, 9, 10,11,12,13,14,15,16
            'wolf' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'werecrow' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'werekitten' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'traitor' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'cultist' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'seer' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'shaman' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'harlot' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'hunter' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'villager' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'crazed shaman' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'cursed villager' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'gunner' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0]}
    },
    'template' : {
        'description' : "This is a template you can use for making your own gamemodes.",
        'min_players' : 0,
        'max_players' : 0,
        'roles' : {
            #4, 5, 6, 7, 8, 9, 10,11,12,13,14,15,16
            'wolf' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'werecrow' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'werekitten' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'traitor' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'cultist' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'seer' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'shaman' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'harlot' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'hunter' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'detective' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'villager' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'crazed shaman' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'cursed villager' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0],
            'gunner' :
            [0, 0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0]}
    }
}
gamemodes['belunga']['roles'] = dict(gamemodes['default']['roles'])

VILLAGE_ROLES_ORDERED = ['seer', 'shaman', 'harlot', 'hunter', 'detective', 'villager']
WOLF_ROLES_ORDERED = ['wolf', 'werecrow', 'werekitten', 'traitor', 'sorcerer', 'cultist']
NEUTRAL_ROLES_ORDERED = ['crazed shaman', 'fool']
TEMPLATES_ORDERED = ['cursed villager', 'gunner']
totems = {'death_totem' : 'Người chơi nhận được bùa này sẽ hi sinh tối nay.',
          'protection_totem': 'Người chơi nhận được bùa này sẽ được bảo vệ đêm nay.',
          'revealing_totem': 'Nếu người nhận được bùa này bị treo cổ, vai của họ sẽ bị lộ thay vì phải chết.',
          'influence_totem': 'Giá trị phiếu bầu của người sở hữu lá bùa này sẽ gấp đôi người thường vào sáng mai.',
          'impatience_totem' : 'Người giữ lá bùa này sẽ vote cho tất cả người chơi trừ họ vào sáng mai, cho dù họ có muốn vote hay không.',
          'pacifism_totem' : 'Người giữ lá bùa này sẽ bỏ phiếu trắng cho tất cả người chơi vào sáng mai dù họ có muốn vote hay không.',
          'cursed_totem' : 'Người sỡ hữu lá bùa này sẽ bị nguyền rủa nếu họ không bị nguyền rủa sẵn.',
          'lycanthropy_totem' : 'Người giữ lá bùa này nếu bị giết bởi sói vào tối nay, họ sẽ không chết mà hóa sói.',
          'retribution_totem' : 'Nếu người giữ lá bùa này bị giết bởi sói vào tối nay thì họ sẽ giết 1 con sói ngẫu nhiên để trả thù.',
          'blinding_totem' : 'Người giữ lá bùa này sẽ bị chấn thương và không thể vote vào sáng mai.',
          'deceit_totem' : 'Nếu người giữ lá bùa này bị soi bởi tiên tri tối nay thì kết quả soi của tiên tri sẽ trái ngược với sự thật '
                           'Nếu tiên tri giữ lá bùa này, kết quả soi tối nay của họ sẽ bị đảo ngược.'}
SHAMAN_TOTEMS = ['death_totem', 'protection_totem', 'revealing_totem', 'influence_totem', 'impatience_totem', 'pacifism_totem', 'retribution_totem']
ROLES_SEEN_VILLAGER = ['werekitten', 'traitor', 'sorcerer', 'cultist', 'villager', 'fool']
ROLES_SEEN_WOLF = ['wolf', 'werecrow', 'cursed']
ACTUAL_WOLVES = ['wolf', 'werecrow', 'werekitten']
WOLFCHAT_ROLES = ['wolf', 'werecrow', 'werekitten', 'traitor', 'sorcerer', 'cultist']

########### END POST-DECLARATION STUFF #############
client.loop.create_task(do_rate_limit_loop())
client.loop.create_task(backup_settings_loop())
client.run(TOKEN)
