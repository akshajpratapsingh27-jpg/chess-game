// uci.c

#include "stdio.h"
#include "defs.h"
#include "tinycthread.h"
#include "string.h"

#define INPUTBUFFER 400 * 6

thrd_t mainSearchThread;
int mainSearchThreadActive = FALSE;

int LaunchSearchThread(thrd_t *thread, S_BOARD *pos, S_SEARCHINFO *info, S_HASHTABLE *table ) {
	S_SEARCH_THREAD_DATA *pSearchData = static_cast<S_SEARCH_THREAD_DATA *>(malloc(sizeof(S_SEARCH_THREAD_DATA)));
	if(pSearchData == NULL) {
		printf("info string unable to allocate search thread data; searching synchronously\n");
		SearchPosition(pos, info, table);
		return FALSE;
	}

	pSearchData->originalPosition = pos;
	pSearchData->info = info;
	pSearchData->ttable = table;

	if(thrd_create(thread, &SearchPosition_Thread, (void*)pSearchData) != thrd_success) {
		free(pSearchData);
		printf("info string unable to create search thread; searching synchronously\n");
		SearchPosition(pos, info, table);
		return FALSE;
	}
	return TRUE;
}

void JoinSearchThread(S_SEARCHINFO *info) {
	if (!mainSearchThreadActive) {
		return;
	}
	info->stopped = TRUE;
	thrd_join(mainSearchThread, NULL);
	mainSearchThreadActive = FALSE;
}

// go depth 6 wtime 180000 btime 100000 binc 1000 winc 1000 movetime 1000 movestogo 40
void ParseGo(const char* line, S_SEARCHINFO *info, S_BOARD *pos, S_HASHTABLE *table) {

	int depth = -1, movestogo = 30,movetime = -1;
	int time = -1, inc = 0;
	const char *ptr = NULL;
	info->timeset = FALSE;

	if ((ptr = strstr(line,"infinite"))) {
		;
	}

	if ((ptr = strstr(line,"binc")) && pos->side == BLACK) {
		inc = atoi(ptr + 5);
	}

	if ((ptr = strstr(line,"winc")) && pos->side == WHITE) {
		inc = atoi(ptr + 5);
	}

	if ((ptr = strstr(line,"wtime")) && pos->side == WHITE) {
		time = atoi(ptr + 6);
	}

	if ((ptr = strstr(line,"btime")) && pos->side == BLACK) {
		time = atoi(ptr + 6);
	}

	if ((ptr = strstr(line,"movestogo"))) {
		movestogo = atoi(ptr + 10);
	}
	if(movestogo <= 0) {
		movestogo = 1;
	}

	if ((ptr = strstr(line,"movetime"))) {
		movetime = atoi(ptr + 9);
	}

	if ((ptr = strstr(line,"depth"))) {
		depth = atoi(ptr + 6);
	}

	if(movetime != -1) {
		time = movetime;
		movestogo = 1;
	}

	info->starttime = GetTimeMs();
	info->depth = depth;

	if(time != -1) {
		info->timeset = TRUE;
		int usableTime = time > 50 ? time - 50 : 1;
		int allocation = usableTime / movestogo;
		int incrementBudget = inc > 0 ? inc - inc / 4 : 0;
		allocation = incrementBudget > usableTime - allocation
			? usableTime
			: allocation + incrementBudget;
		if(allocation < 1) {
			allocation = 1;
		}
		info->stoptime = info->starttime + allocation;
	}

	if(depth == -1) {
		info->depth = MAXDEPTH - 1;
	} else {
		if(info->depth < 1) {
			info->depth = 1;
		}
		if(info->depth >= MAXDEPTH) {
			info->depth = MAXDEPTH - 1;
		}
	}

	JoinSearchThread(info);

	info->stopped = FALSE;
	mainSearchThreadActive = LaunchSearchThread(&mainSearchThread, pos, info, table);
}

// position fen fenstr
// position startpos
// ... moves e2e4 e7e5 b7b8q
void ParsePosition(const char* lineIn, S_BOARD *pos) {

	lineIn += 9;
    const char *ptrChar = lineIn;

    if(strncmp(lineIn, "startpos", 8) == 0){
        ParseFen(START_FEN, pos);
    } else {
        ptrChar = strstr(lineIn, "fen");
        if(ptrChar == NULL) {
            ParseFen(START_FEN, pos);
        } else {
            ptrChar+=4;
            ParseFen(ptrChar, pos);
        }
    }

	ptrChar = strstr(lineIn, "moves");
	int move;

	if(ptrChar != NULL) {
        ptrChar += 6;
        while(*ptrChar) {
              move = ParseMove(ptrChar,pos);
			  if(move == NOMOVE) break;
			  MakeMove(pos, move);
              pos->ply=0;
              while(*ptrChar && *ptrChar!= ' ') ptrChar++;
              ptrChar++;
        }
    }
}

void Uci_Loop(S_BOARD *pos, S_SEARCHINFO *info) {

	setbuf(stdin, NULL);
    setbuf(stdout, NULL);

	char line[INPUTBUFFER];
    printf("id name %s\n",NAME);
    printf("id author Bluefever\n");
	printf("option name Hash type spin default 256 min 4 max %d\n",MAX_HASH);
	printf("option name Threads type spin default %d min 1 max %d\n",info->threadNum,MAXTHREADS);
	printf("option name Book type check default %s\n",EngineOptions->UseBook ? "true" : "false");
    printf("uciok\n");
	
	int MB = 64;

	while (TRUE) {
		memset(&line[0], 0, sizeof(line));
        fflush(stdout);
        if (!fgets(line, INPUTBUFFER, stdin)) {
			info->quit = TRUE;
			JoinSearchThread(info);
			break;
		}

        if (line[0] == '\n')
        continue;

        if (!strncmp(line, "isready", 7)) {
            printf("readyok\n");
            continue;
        } else if (!strncmp(line, "position", 8)) {
            ParsePosition(line, pos);
        } else if (!strncmp(line, "legalmoves", 10)) {
        	S_MOVELIST list[1];
        	GenerateAllMoves(pos, list);
        	printf("info string legalmoves");
        	for(int i = 0; i < list->count; ++i) {
        		int move = list->moves[i].move;
        		if(MakeMove(pos, move)) {
        			printf(" %s", PrMove(move));
        			TakeMove(pos);
        		}
        	}
        	int inCheck = SqAttacked(pos->KingSq[pos->side], pos->side ^ 1, pos);
        	printf(" status %s\n", inCheck ? "check" : "safe");
        } else if (!strncmp(line, "ucinewgame", 10)) {
			ClearHashTable(HashTable);
            ParsePosition("position startpos\n", pos);
        } else if (!strncmp(line, "go", 2)) {
            ParseGo(line, info, pos, HashTable);
        } else if (!strncmp(line, "run", 3)) {
            ParseFen(WAC_2, pos);
            ParseGo("go infinite", info, pos, HashTable);
        } else if (!strncmp(line, "stop", 4)) {
			JoinSearchThread(info);
        } else if (!strncmp(line, "quit", 4)) {
            info->quit = TRUE;
			JoinSearchThread(info);
            break;
        } else if (!strncmp(line, "uci", 3)) {
            printf("id name %s\n",NAME);
            printf("id author Bluefever\n");
            printf("option name Hash type spin default 256 min 4 max %d\n",MAX_HASH);
            printf("option name Threads type spin default %d min 1 max %d\n",info->threadNum,MAXTHREADS);
            printf("option name Book type check default %s\n",EngineOptions->UseBook ? "true" : "false");
            printf("uciok\n");
        } else if (!strncmp(line, "debug", 4)) {
            DebugAnalysisTest(pos,info,HashTable);
            break;
        } else if (!strncmp(line, "setoption name Hash value ", 26)) {			
			sscanf(line,"%*s %*s %*s %*s %d",&MB);
			if(MB < 4) MB = 4;
			if(MB > MAX_HASH) MB = MAX_HASH;
			InitHashTable(HashTable, MB);
		} else if (!strncmp(line, "setoption name Threads value ", 29)) {			
			sscanf(line,"%*s %*s %*s %*s %d",&MB);
			if(MB < 1) MB = 1;
			if(MB > MAXTHREADS) MB = MAXTHREADS;
			info->threadNum = MB;
		} else if (!strncmp(line, "setoption name Book value ", 26)) {
			char *value = strstr(line, "value ");
			if(value != NULL) {
				value += 6;
				EngineOptions->UseBook = !strncmp(value, "true", 4);
			}
		}
		if(info->quit) break;
    }
}








