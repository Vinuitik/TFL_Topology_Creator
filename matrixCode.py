import random

n = int(input("Please enter size of the board: "))
flipping_prob = 0.3

matrix = [ [0 for _ in range(n)] for _ in range(n) ]

y_player = random.randint(0,n-1)
x_player = random.randint(0,n-1)
matrix[y_player][x_player] = 2

def print_matrix(mat):
    for row in mat:
        print(" ".join(str(x) for x in row))

def up():
    global y_player, x_player
    if y_player == 0:
        print("You hit the ceiling")
        return ;
    if matrix[y_player-1][x_player]==1:
        print("You hit the wall")
        return ;
    matrix[y_player-1][x_player] = 2
    matrix[y_player][x_player] = 0 
    
    y_player-= 1

for i in range(n):
    for j in range(n):
        if matrix[i][j] == 0 and random.random()<flipping_prob:
            matrix[i][j] = 1
            
finish = False
while not finish:
    print("-"*50)
    print_matrix(matrix)
    action = input("Where would you like to go?\n")
    action = action.lower()
    if action != "up" and action!="down" and action!="left" and action!="right":
        print("Try again!")
        continue
    if action == "up":
        up()



